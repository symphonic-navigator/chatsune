"""System prompt extension injected for the ``screen_effect`` integration.

Kept in its own module so the (long) string lives outside the registry file
and can be edited without diff churn on the registration call.
"""

SCREEN_EFFECT_PROMPT = '''<screeneffects priority="normal">
You may emit small visual flourishes inline using the markup:

  <screen_effect rising_emojis 💖 🤘 🔥>

Available effects:
  - rising_emojis EMOJI [EMOJI ...] — a gentle upward shower of the given
    emojis (1..5), drifting and varying in size. Pass between 1 and 5
    distinct emojis.

Use sparingly — once per response at most, and only when it genuinely fits
the moment (a celebration, a flirt, a punchline). The user sees a small
monospace pill in chat at the spot where the tag appeared, and the effect
plays over the whole screen briefly. Effects are silent and never carry
prose meaning — your words still need to do the talking.
</screeneffects>'''
