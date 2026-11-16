# Leverage, and why this book uses none

Currencies move less than stocks, so dealers lend you most of the money for a trade. That loan is **leverage**, and it's where most forex losses start.

## How much US dealers may lend

A US dealer must collect a deposit of at least 2% of a trade's value on the major pairs and 5% on the others ([eCFR](https://www.ecfr.gov/current/title-17/chapter-I/part-5/section-5.9)). That works out to leverage of up to 50:1 and 20:1 ([OANDA](https://oanda.com/us-en/trading/spreads-margin)).

At 50:1, a $2,000 deposit controls $100,000 of EUR/USD. A 2% move against you, which a major pair can make in a bad week, wipes out the whole deposit: 50 × 2% = 100%. Profits are multiplied the same way, which is the attraction, but the CFTC reports that about two out of three retail forex traders lose money each quarter ([CFTC](https://www.cftc.gov/LearnAndProtect/forexfrauds)).

## The forex book: fully paid for

The forex book treats every position as if you'd paid for it in full, shorts included:

- With the standard pairs, each pair may take up to 14% of the account and the book holds at most seven, so a new position always uses money the account has. The exotic pairs get 10% each, six at most.
- Buying power is equity minus what's already held or waiting on an order. The leverage the dealer offers is simply never used.

Financing comes out of the same money, so with every slot filled, the free cash can slip a little below zero. Then no new position starts until there's room again.

The price of that choice: unleveraged currency trading moves slowly, so expect modest numbers, up or down. That's the right speed for learning.

## Sizing a trade

The rules are the ones you know from stocks ([Position sizing](#/learn/position-sizing)): risk at most 1% of the account per trade, with the recommended stop 3% from the entry on the standard pairs. Risk alone would allow a position of a third of the account (1% ÷ 3%), so the 14% cap decides.

With $100,000 and EUR/USD at 1.1000:

| Step | Value |
| --- | --- |
| Limit price (0.1% above) | 1.10110 |
| Size: 14% of $100,000 ÷ 1.10110 | 12,714 units (about $14,000) |
| Stop (3% below the limit) | 1.06807 |
| Loss if the stop fills | about $420, or 0.42% of the account |

A short mirrors it: the limit sits a little below the price and the stop 3% above.

When the dollar comes first, as in USD/JPY, a unit is one dollar, so $14,000 buys 14,000 units, and the profit or loss, which comes in yen, is counted back into dollars. A loss at the stop then comes to slightly more than 3% of the position, and the app trims the order if that would break the 1% limit.

## A wider stop

You can widen the stop under **Your settings**. The app shows what it means first: each stop-out can cost more, up to the 1% limit per trade, and past that point positions shrink so a stop-out stays inside it. Positions already open keep the stop they have.

## Seven pairs, one dollar

Every pair has the dollar on one side. When the dollar strengthens broadly, the pairs tend to move together, so several positions can behave more like one big bet on the dollar than separate bets. The cap on open positions and the 2% daily loss limit matter more here, not less ([Limits and diversification](#/learn/limits-and-diversification)).
