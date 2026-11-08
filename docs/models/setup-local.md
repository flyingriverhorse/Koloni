# Set up a local model

A model on your own machine spends no money and sends nothing out. KOLONİ talks to it through the
OpenAI API, so the model server must support tool calls.

## llama.cpp

KOLONİ is built and tested with llama.cpp's `llama-server`. Start it with `--jinja`, so that tool calls
work. Its usual address is `http://127.0.0.1:8080/v1`.

At the first start, KOLONİ makes a provider called "Local" at that address (or at
`KOLONI_MODEL_BASE_URL`). It counts as set up only while its server answers.

### Starting the server from KOLONİ

For an OpenAI-compatible provider whose address is on this machine, the provider's window has a
**Server** tab:

- **Program**: your `llama-server` program.
- **Model**: a model file, or none.
- **Context (-c)**, **GPU layers (-ngl)**, **Default thinking**, **Temperature**, **Top-p**, **Top-k**,
  **Min-p**.
- **Advanced: every other argument, as given**.

The tab's first values are only a starting point: the `llama-server` on your PATH (if there is none,
set **Program** to its full path), `--port 8080 --jinja`, and no model. For your own build, set
**Program** to the full path of `llama-server` in its `bin` folder. **Model** lists the `.gguf` files in
the `models` folder next to that program. KOLONİ keeps the tab's values when you press **Start** or
**Restart**, in `local-server.json` under `runtime/`; until then, `KOLONI_LOCAL_SERVER` can name the
program (see [Environment variables](../reference/environment.md)).

Check the values for your machine, then press **Start**. The tab
shows whether it runs, the GPU's memory and load (from `nvidia-smi`), and **Server output**. "It starts
only when you press Start, and stops when KOLONİ closes. No agent can start it; Start runs exactly what
is shown here."

**At most this many agents at once**: for a server on this machine, KOLONİ reads the server's slots when
its first agent starts.

## Other model servers

Any server that speaks the OpenAI API and supports tool calls can be added the same way: Models → **Add a
provider** → **OpenAI-compatible server**, with its address. Such servers (Ollama, …) should work but are
not tested: the local server KOLONİ is measured with is llama.cpp's `llama-server`. KOLONİ has no
settings of its own for those servers, and the **Server** tab starts only `llama-server`. Press **Test**
to see whether the model can use tools.

## After adding

- Give the models a **Tier** and set **Agents may use** on the **Models** tab. See
  [Tiers and Agents may use](tiers.md).
- "A model server on this machine spends no money and has no plan: there is nothing to limit."
- If the model takes long to load, raise `KOLONI_MODEL_FIRST_TOKEN_SECONDS`. See
  [Environment variables](../reference/environment.md).
