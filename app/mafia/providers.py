"""Назначение моделей местам независимо от игровых ролей."""


def player_models(default_model, *, gemini=None, gemini_ids=(), local=None, local_id='p5'):
    seats = [f'p{i}' for i in range(1, 11)]
    google = list(gemini_ids)
    if len(google) != len(set(google)) or not set(google).issubset(seats):
        raise ValueError('Gemini: нужны уникальные места p1..p10')
    if google and gemini is None:
        raise ValueError('Для выбранных игроков нужна модель Gemini')
    if local is not None and (local_id not in seats or local_id in google):
        raise ValueError('Место GGUF должно быть p1..p10 и не пересекаться с Gemini')
    result = dict.fromkeys(seats, default_model)
    result.update({pid:gemini for pid in google})
    if local is not None:
        result[local_id] = local
    return result
