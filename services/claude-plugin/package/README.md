# Zynd for Claude

Connects Claude to your private Zynd facts and your public Zynd card at
https://cards.zynd.ai.

- **Recall on request.** Ask Claude what Zynd remembers about a topic and it
  returns the matching private facts. Claude never recalls on its own.
- **Propose, never save.** Claude can draft one exact fact for you. A draft is
  temporary: you save it privately, or confirm the exact public wording for your
  card, after signing in on cards.zynd.ai. Chat agreement cannot do either.
- **See what is public.** Claude can show the facts already on your card and the
  ones still pending your review.

The plugin adds three skills (`zynd-context`, `zynd-memory`, `zynd-card`) and
connects the Zynd server at `https://api.zynd.ai/claude/mcp`. Sign-in happens in
your browser the first time Claude uses a Zynd tool. It has no hooks, commands or
agents, and it cannot export, delete, message anyone or publish for you.

Documentation: https://cards.zynd.ai/claude · Support: https://cards.zynd.ai/support
· Privacy: https://cards.zynd.ai/privacy · Terms: https://cards.zynd.ai/terms
