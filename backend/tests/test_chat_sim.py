"""The terminal simulator wires the real conversation rules to fake data and keeps history."""

from app.agents.message_interpreter import MessageDecision
from app.agents.request_interpreter import RequestDecision
from app.cli import chat_sim
from app.core.settings import Settings


class Interpreter:
    def __init__(self):
        self.histories = []
        self.requests = []

    def interpret(self, text, tasks, *, history=(), focus_task_id=None):
        self.histories.append(list(history))
        return MessageDecision(
            intent="answer", task_ids=[], completion_asserted=False, evidence_quote="",
            confidence=1.0, reply=f"echo: {text}",
        )


class Accepting(Interpreter):
    def interpret_request(self, text, requests, **_):
        self.requests.append(list(requests))
        return RequestDecision(
            action="accepted", request_no=8, execute=True, confidence=1.0, evidence_quote=text,
        )


def drive(lines, interpreter, reworder=None, **settings_overrides):
    feed = iter(lines)
    out = []
    settings = Settings(
        message_ai_enabled=True, message_memory_enabled=True, help_workflow_enabled=True, **settings_overrides,
    )
    code = chat_sim.run(lambda prompt: next(feed), out.append, interpreter, settings, reworder=reworder)
    return code, "\n".join(out)


def test_a_plain_reply_accepts_the_seeded_request_in_the_simulation():
    interpreter = Accepting()
    code, output = drive(["please accept the lunch transfer", "/requests", "/quit"], interpreter)
    assert code == 0
    assert interpreter.requests[0][0]["request_no"] == 8
    assert "Accepted the transfer" in output and "no pending requests" in output


def test_notify_shows_the_template_and_its_reworded_version():
    _, output = drive(["/notify", "/quit"], Interpreter(), reworder=lambda text: "Hi! " + text)
    assert "Hi! Winnie REQ-8" in output and "template:" in output.lower()


def test_second_turn_sees_the_first_exchange_in_the_production_format():
    interpreter = Interpreter()
    code, output = drive(["what is due?", "the sponsor one", "/quit"], interpreter)
    assert code == 0
    assert interpreter.histories[0] == []
    second = interpreter.histories[1]
    assert second == [{"role": "user", "content": "what is due?"},
                      {"role": "assistant", "content": "echo: what is due?"}]
    assert "echo: the sponsor one" in output


def test_reset_clears_the_remembered_exchanges():
    interpreter = Interpreter()
    drive(["what is due?", "/reset", "and now?", "/quit"], interpreter)
    assert interpreter.histories[1] == []


def test_memory_keeps_only_the_configured_number_of_exchanges():
    interpreter = Interpreter()
    drive(["old message", "recent message", "another message", "new question", "/quit"],
          interpreter, message_memory_max_turns=2)
    kept = [turn["content"] for turn in interpreter.histories[-1] if turn["role"] == "user"]
    assert kept == ["recent message", "another message"]


def test_unknown_commands_and_empty_lines_are_harmless():
    interpreter = Interpreter()
    code, output = drive(["", "/nope", "/tasks", "/quit"], interpreter)
    assert code == 0 and interpreter.histories == []
    assert "Unknown command" in output and "Book room" in output
