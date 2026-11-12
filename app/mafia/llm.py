from dataclasses import replace
from app.llm import ChatCompletionsModel

class LlamaCppModel(ChatCompletionsModel):
    """GGUF через уже запущенный llama.cpp. Модель одна, роль назначает движок."""
    def complete_json(self, messages, schema, name):
        request = replace(self,options={**self.options,'response_format':{'type':'json_object','schema':schema}})
        return ChatCompletionsModel.complete(request,messages)
