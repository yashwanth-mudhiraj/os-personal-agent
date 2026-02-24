from model_config import load_model
import json
import re

class SimpleAgent:

    def __init__(self):

        self.system_prompt = """You are a helpful voice assistant running on a Windows PC.

                        Your job is to analyze the user's spoken input and return a LIST of structured actions.

                        You MUST respond strictly in valid JSON format.
                        Return ONLY a JSON array.
                        Do NOT include markdown.
                        Do NOT include explanations.
                        Do NOT include text outside the JSON array.

                        Available intents:

                        1. System control:
                        {
                        "intent": "system",
                        "type": "app | file | folder",
                        "action": "open | close | focus | maximize | minimize | list",
                        "target": "this | it | ..name of app/file/folder..",
                        "response": "verbal confirmation text to say back to the user"
                        }

                        2. Chat:
                        { "intent": "chat", "response": "your concise and natural reply here" }

                        IMPORTANT:
                        - ALWAYS wrap your response in a JSON array.
                        - Even for one item, return a list.
                        - Never return plain text.

                        Example for chat:
                        User: tell me a joke
                        Response:
                        [
                        { "intent": "chat", "response": "Why did the computer go to therapy? It had too many bytes of trauma." }
                        ]
                        """
        
        # FIX: We removed the line that was overwriting your prompt, 
        # and we are now actually loading the model!
        self.model = load_model()

    def chat(self, user_text: str) -> list: # Changed return type hint to list
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_text}
        ]
        
        raw_response = self.model.generate(messages) 
        cleaned_response = re.sub(r'^```json\s*|\s*```$', '', raw_response.strip(), flags=re.IGNORECASE)
        
        try:
            # This will now be a list of dictionaries
            actions = json.loads(cleaned_response)
            return actions if isinstance(actions, list) else [actions]
        except json.JSONDecodeError:
            return [{"intent": "chat", "response": "I'm sorry, I couldn't process that command."}]
        
if __name__ == "__main__":
    agent = SimpleAgent()
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit": break

        responses = agent.chat(user_input)
        
        print("\nAgent processing tasks:")
        for task in responses:
            if task['intent'] == 'command':
                print(f"  -> EXECUTING: {task['action']} on {task['target']}")
                # Here is where you'd call: os.system(f"start {task['target']}")
            else:
                print(f"  -> SAYING: {task['response']}")
        print("-" * 60)