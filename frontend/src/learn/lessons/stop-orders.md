# Stops, gaps and one-triggers-other orders

A **stop order**, often called a stop-loss, waits at a price you choose below the market. If the price falls to that level, it turns into a market order and sells ([Investor.gov](https://www.investor.gov/additional-resources/news-alerts/alerts-bulletins/investor-bulletin-stop-stop-limit-trailing-stop)).

## Why every position has one

A stop caps how much one trade can lose in normal trading. In this app every stock buy carries a stop 8% below its limit price. A buy at $600.00 gets a stop at $552.00, and if the price falls there, the stop sells. A forex short has its stop above the entry, since it loses when the price rises.

## Choosing your own stop

Each book recommends a stop: 8% for stocks, 15% for crypto, 3% for the standard forex pairs and 5% for the exotic ones. You can change it under **Your settings**. A tighter stop gets hit by ordinary swings more often. A wider one lets losses run further before the app gets you out, so the app shows you what it means first and asks you to confirm: how much a stop-out could cost, and, once the 1% limit per trade bites, how much smaller new positions get. Positions already open keep the stop they have.

## Gaps: when a stop sells below its price

A stop is a trigger, not a promise. Once triggered it sells at the next available price, which can be well below the stop price in a fast market or after bad overnight news.

Say that position closes at $560.00 and opens the next morning at $530.00 after bad news. The stop at $552.00 triggers at the open and sells near $530.00, not $552.00. FINRA suggests weighing this before relying on stops in volatile markets ([FINRA](https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets)).

A **stop-limit** order adds a limit price so it can't sell too low, but then it may not sell at all while the price keeps falling. For stocks the app uses plain stops, because getting out matters more than the exact price. Crypto is the exception: Alpaca's crypto desk takes stop-limits but not plain stops ([How trading crypto differs](#/learn/crypto-trading-differs)). Forex entries carry a plain stop-loss, like stocks ([How trading forex differs](#/learn/forex-trading-differs)).

## One-triggers-other (OTO)

The app sends each stock buy as an OTO order: the buy, plus a stop that switches on the moment the buy fills. The stop lives at the broker, so it protects you even when your computer is off.

When the rule says sell, the app first cancels that stop, then sends the sell. The broker would otherwise refuse the sell, because the stop has already reserved the shares.
