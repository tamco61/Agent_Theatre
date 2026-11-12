"""Продолжение после сбоя обычной дневной речи; другие фазы не переигрываем."""
from pathlib import Path
from uuid import uuid4
from .voting import Voting


def finish_day(game):
    s = game.state
    if not s.nominees or (s.day == 1 and len(s.nominees) == 1):
        game.emit('no_vote', 'Голосования нет: '+(
            'никого не выставили.' if not s.nominees else 'единственный кандидат в первый день.'))
        return
    game.eliminate(Voting(game).run(list(s.nominees)))
    game.finish_if_won()


def resume_discussion(game):
    """Только живой объект game в том же kernel, после ошибки обычной речи."""
    s = game.state
    if s.status != 'failed' or s.phase != 'discussion' or not s.prepared:
        raise ValueError('Продолжение поддержано только после сбоя обычной дневной речи, в том же ядре')
    living = [p.id for p in s.players if p.alive]
    if s.first_speaker_id not in living or not 1 <= s.day <= game.config.max_days:
        raise ValueError('Некорректная точка продолжения')
    start = living.index(s.first_speaker_id)
    order = living[start:] + living[:start]
    done = [e.speaker_id for e in s.events if e.day == s.day and e.kind == 'speech']
    if done != order[:len(done)]:
        raise ValueError('Записанные речи не совпадают с началом текущего круга')
    if any(e.day == s.day and e.kind in ('ballot_candidate','vote','elimination') for e in s.events):
        raise ValueError('Голосование уже начиналось; повторять его этим способом нельзя')
    # Сохранить точный снимок до смены статуса. Секреты остаются в приватном файле.
    directory = Path(game.writer.directory)
    game.writer.save(game.config, s)
    backup = directory / ('private_before_resume_'+uuid4().hex[:10]+'.json')
    backup.touch(mode=0o600)
    backup.write_bytes((directory/'private_result.json').read_bytes())
    backup.chmod(0o600)
    game.writer.journal.emit('run_recovery', {'day':s.day, 'phase':s.phase,
        'accepted_speakers':done, 'pending_speakers':order[len(done):], 'backup':backup.name})
    s.status, s.error = 'running', None
    game.writer.save(game.config, s)
    try:
        for pid in order[len(done):]:
            game.speech(pid)
        finish_day(game)
        if s.status == 'running':
            game.night()
        for day in range(s.day+1, game.config.max_days+1):
            if s.status != 'running':
                break
            s.day = day
            game.day()
            if s.status == 'running':
                game.night()
        if s.status == 'running':
            s.phase, s.status = 'finished', 'limited'
            game.emit('limit', 'Партия прервана по техническому лимиту дней; игровой результат не определён.')
    except (Exception, KeyboardInterrupt) as exc:
        s.status, s.error = 'failed', str(exc) or type(exc).__name__
        raise
    finally:
        game.writer.save(game.config, s)
    return s
