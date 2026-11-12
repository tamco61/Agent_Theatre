# 2. Скачать выбранный GGUF с явной авторизацией и проверкой доступа.
from pathlib import Path
import os
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import HfHubHTTPError

# Явно выбранная новая конверсия того же upstream; это не файл прежней партии.
REPO = "Sakura721/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF"
FILE = "DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-Q4_K_M.gguf"
REVISION = "35285bf9d161fb3a9f28aee914670b0b32e72f3d"
HF_SECRET_NAME = "hg_api_key"  # Имя секрета Hugging Face в нашей Kaggle-сессии.

try:
    from kaggle_secrets import UserSecretsClient
    hf_token = UserSecretsClient().get_secret(HF_SECRET_NAME).strip() or False
except Exception:
    # token=False исключает неявное использование старого сохранённого токена.
    hf_token = os.environ.get("HF_TOKEN", "").strip() or False

print("Источник GGUF:", REPO)
print("Файл:", FILE)
api = HfApi(token=hf_token)
if hf_token:
    try:
        api.whoami()
    except HfHubHTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            raise RuntimeError("HF-токен отклонён. Обновите секрет hg_api_key: нужен действующий токен Hugging Face.") from None
        raise RuntimeError(f"Не удалось проверить HF-токен (HTTP {status}); веса не скачивались.") from None

try:
    api.model_info(REPO, revision=REVISION)
except HfHubHTTPError as exc:
    status = getattr(exc.response, "status_code", None)
    if status in (401, 403, 404):
        detail = ("Токен действителен, но доступа к выбранному репозиторию/ревизии нет."
                  if hf_token else "Анонимный доступ недоступен. Включите Kaggle Secret hg_api_key и повторите ячейку.")
        raise RuntimeError(detail + " Проверьте страницу модели под своим HF-аккаунтом; веса автоматически не заменяются.") from None
    raise RuntimeError(f"Не удалось проверить репозиторий (HTTP {status}); веса не скачивались.") from None

MODEL = Path(hf_hub_download(REPO, FILE, revision=REVISION,
                           local_dir=ROOT / "models", token=hf_token))
print("Файл:", MODEL.name)
print("Ревизия:", REVISION)
print("Размер:", round(MODEL.stat().st_size / 1e9, 2), "GB")
