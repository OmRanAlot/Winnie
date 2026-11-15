# Replace just the stale test at the bottom of backend/tests/test_gemini.py:
# def test_flash_38_uses_low_thinking(client, gemini, configure):
# with the block below.

def test_flash_38_uses_medium_thinking(client, gemini, configure):
    configure(model="gemini-3.8-flash")
    response = post(client)
    assert response.status_code == 200
    assert gemini.calls[0]["config"].thinking_config.thinking_level == route.types.ThinkingLevel.MEDIUM
