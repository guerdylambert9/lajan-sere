# Backtests and their traps

A **backtest** runs a rule over past prices as if you had traded it, costs included. It's the cheapest way to throw out bad ideas, and the easiest way to fool yourself.

## The traps

- **Overfitting.** Try enough variations and one will look great by luck alone. The defense is few parameters, chosen for a reason, plus a check that nearby settings work about as well. Gate 1 moves each parameter about 20% each way.
- **Look-ahead bias.** Using information you couldn't have had at the time, such as trading at a price before it happened. This app's backtester lets a rule see only the closes up to the day it decides.
- **Survivorship bias.** Testing today's list of winners on past data. Companies that failed or were dropped aren't on today's list, so the test looks better than reality. Fixed lists such as these ETFs avoid it.
- **Ignoring costs.** Every trade costs something in spreads and slippage. The backtester charges 5 basis points (0.05%) on every buy and every sell.

## Held-out years

The app develops on 2016 to 2022 and keeps 2023 to today unseen. Gate 1 looks at those held-out years once per idea. Peek and tweak repeatedly and the held-out years stop being a fair test, so the app logs every look.

## A day late

Live orders go out the morning after a signal. Gate 1 checks that a rule still works when every trade happens a full day later, so it doesn't depend on perfect timing.

## AI is judged going forward

A language model may already know what happened after the dates in a backtest, so its backtests can look better than it really is. The optional AI notes are judged only on results logged from now on.
