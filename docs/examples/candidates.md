# Picking the best of several candidates

Give one job to several agents, score each result, and keep the best. The ready recipe **Evolve** does
this with three Coders.

1. **Set a measure command.** Settings › This project › Checks and git › **Measure command**: a command whose last
   line of output is a number from 0 to 100, for example `python measure.py`. Higher is better.
2. **Make the recipe.** Agents → **Recipes**: pick **Evolve** and press **Copy it**, or draw your own
   step whose **Who** is **Candidates (the best one goes on)**. Choose how many (2 to 5), their models
   (**Auto, the Lead picks**, **Same model** or **I pick each**), and a **Target** score if you want one.
   With a loop, the step is tried again while the best score is below the target.
3. **Use it.** On the canvas, **Teams for this chat** → **Manual**, pick a team and this recipe. Then
   write your message.
4. **Pick the winner.** Each candidate works in its own copy and is scored. A card lists the scores and
   asks which candidate's work goes on. At Full auto the best score goes on by itself.
5. **Take it in** on the **Teams' work is ready** card.

A new round's result replaces the kept one only if it scores higher.

See [Recipes and candidates](../agents/recipes.md).
