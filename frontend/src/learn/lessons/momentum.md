# Momentum

**The rule:** on the first trading day of each month, rank the ETFs by their return over the 12 months before the latest month, and own the top 3 if that return is positive.

## Why it can work

Assets that rose the most over the past year have tended to keep doing better than the rest for a few more months. Jegadeesh and Titman documented this for US stocks in 1993 ([Journal of Finance](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)), and later research found strong average returns from momentum across many asset classes ([Daniel and Moskowitz](https://www.nber.org/papers/w20439)).

Researchers usually leave out the latest month, because very recent winners tend to give back a little in the short run.

## When it struggles

Momentum can crash. Daniel and Moskowitz found that the worst crashes come in panicky markets: after a fall, when volatility is high, during a sharp rebound ([Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2015.12.002)). In those rebounds, last year's losers jump while last year's winners lag.

This app's version only buys winners and never bets against losers, and it skips anything with a negative return, so it can sit in cash. That softens a crash but doesn't prevent one.

## Monthly, on purpose

The rule changes holdings once a month, so a call can say Hold even when a symbol has slipped in today's ranking. The card shows both the rank at the last rebalance and today's.

## The scanner uses the same ranking

The watchlist scanner ranks your watchlist this way every evening, so its buy ideas are what this rule would pick from that list today ([reading a recommendation](#/learn/reading-a-recommendation)).
