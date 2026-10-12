import openai
import openai.error
from typing import List, Dict
import llm_backend
import logging
import time
import traceback
import tiktoken
from multiprocessing import Value
import rich
import rich_utils
logger = logging.getLogger(__name__)

console = rich.get_console()

SYSTEM_MESSAGE = "You are a smart contract auditor. You will be asked questions related to code properties. You can mimic answering them in the background five times and provide me with the most frequently appearing answer. Furthermore, please strictly adhere to the output format specified in the question; there is no need to explain your answer."

encoder = tiktoken.get_encoding("cl100k_base")
encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")

tokens_sent = Value("d", 0)
tokens_received = Value("d", 0)
tokens_sent_gpt4 = Value("d", 0)
tokens_received_gpt4 = Value("d", 0)

# Number of LLM calls actually issued (or, in --dry-run, that WOULD be issued).
num_llm_calls = Value("i", 0)
# Calls skipped because a hard budget guard tripped mid-scan.
num_calls_skipped_budget = Value("i", 0)
# Reason string once a budget guard tripped (parent process only); None = ok.
budget_exceeded_reason = None

# Calls suppressed because the SmartBugs deadline passed. Kept apart from
# num_calls_skipped_budget so the metadata can say WHY a run stopped early.
num_calls_skipped_deadline = Value("i", 0)

# Set once in the parent process when the deadline guard first trips; None means
# it never did. Plain global, not a Value: only the parent ever writes it, the
# same way budget_exceeded_reason works.
deadline_exceeded_reason = None


class Chat:
    def __init__(self) -> None:
        self.currentSession:List[Dict[str,str]] = []
    
    def newSession(self) -> None:
        self.currentSession = []
    
    def sendMessages(self, message:str, GPT4=False) -> str:

        # logger.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        # logger.info(f"Sending message: \n{message}")
        # logger.info(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        
        self.currentSession.append({"role": "system", "content": SYSTEM_MESSAGE})
        self.currentSession.append({"role": "user", "content": message})
        # Point the SDK at the active provider (sets api_key + api_base) and
        # pick the model for this tier (cheap by default, strong when GPT4).
        llm_backend.configure_sdk(openai)
        model = llm_backend.resolve_model(gpt4=GPT4)
        while True:
            try:
                response = openai.ChatCompletion.create(
                    model=model,
                    messages=self.currentSession,
                    temperature=0,
                    top_p=1.0
                )
                break
            except openai.error.RateLimitError as e1:
                logger.warning("Trigger rate limit error, sleep 30 sec")
                time.sleep(30)
            except openai.InvalidRequestError as e2:
                if e2.code == 'context_length_exceeded':
                    logger.error("Too long context, skip")
                    return "KeySentence: ", {}
                else:
                    logger.warning("Retry")
            except openai.error.APIConnectionError as e3:
                logger.warning("API Connection Error, Retry")
            except openai.error.Timeout as e4:
                logger.warning("Timeout, Retry")
            except openai.error.APIError as e5:
                if "502" in e5._message:
                    logger.warning("502 Bad Gateway, Retry")
                    logger.warning(traceback.format_exc())
        # response = openai.Completion.create(
        #     # model="gpt-3.5-turbo",
        #     model="text-davinci-003",
        #     messages = self.currentSession,
        #     # temperature = 0.3
        # )

        content = response['choices'][0]['message']['content']
        self.currentSession.append(response['choices'][0]['message'])

        console.print(rich_utils.make_response_panel(content, "Response"))

        # Return the actual API usage alongside the content. Token accounting is
        # done parent-side in analyze_pipeline.ask_with_timeout (so counts cross
        # the multiprocessing boundary on every platform). Reasoning models
        # (e.g. deepseek-v4-flash) bill completion tokens that are NOT present in
        # `content`, so a text-based estimate would badly undercount -- we use
        # the API's usage when it is provided and fall back to estimation only
        # when it is absent.
        usage = response.get('usage') or {}
        usage_d = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        return content, usage_d
    
    def makeYesOrNoQuestion(self, question:str)->str:
        prompt = f"{question}. Please answer in one word, yes or no."
        return prompt
    
    def makeCodeQuestion(self, question:str, code:str):
        prompt = f'Please analyze the following code, and answer the question "{question}"\n{code}'
        return prompt
