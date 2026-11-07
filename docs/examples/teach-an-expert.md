# Teaching an expert

An expert is a role that knows one topic from its sources, advises and reads only.

1. **Make the expert.** Agents → **New role** → **An expert**. Fill in **Knows** with the topic, and its
   sources, one a line: a docs site's address, files or a folder in the project. Press **Create
   expert**. The role is named "*topic* expert".
2. **Let it learn.** On the Knowledge page, the topic's card shows what learning may cost beside
   **Learn**. Set **At most this much a learning (USD)** and **Learn with** (the model that writes the
   guide) if you want, then press **Learn**. KOLONİ reads the pages and a model writes a short guide.
3. **Check what it learned.** Open the card: **Guide** shows the guide, **Pages** what was read and
   skipped, and **Not known yet** what it could not answer. Press **Try it** and ask what an agent
   would.
4. **Give it more** if needed: add sources on its **Settings** tab and press **Learn more**. Learning
   again reads only what changed.
5. **Use it.** The Orchestrator opens the expert when a job needs the topic. Other roles can use the
   same knowledge too: on a role's **Knowledge** tab, switch it on as **Map**.

When the guide has no answer, an expert with **Agents may search the web when it has no answer** may
search; below Full auto that asks you first. What it finds can be added to the guide on a card.

See [Knowledge and experts](../knowledge.md).
