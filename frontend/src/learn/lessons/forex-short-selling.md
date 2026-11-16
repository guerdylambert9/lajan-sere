# Selling short: betting on a pair falling

Buying EUR/USD pays off when the euro rises against the dollar. **Selling it short** pays off when the euro falls. In forex that's an ordinary trade: every trade buys one currency and sells the other, so selling EUR/USD simply swaps euros for dollars, with nothing to borrow first ([IG](https://www.ig.com/en-ch/learn-to-trade/ig-academy/the-basics-of-forex-trading/how-to-short-forex)).

The forex book can sell short, but only once you switch it on under **Your settings** on the Forex tab. It stays off until you do, and the app shows you the warnings before the change takes effect.

## What the book does with it on

The trend rule becomes two-sided. A pair that closes above its 200-day average is bought, as before. A pair that closes below it is sold short, at the same size. When the signal ends, the book proposes buying it back, which is called **covering**. A long whose signal turns short is closed first, and the short opens on a later day.

| | Long | Short |
| --- | --- | --- |
| Opens with | a buy | a sell |
| Gains when the pair | rises | falls |
| Stop-loss | 3% below the entry | 3% above the entry |
| Closes with | a sell | a buy |

Every short is sized like a long and fully paid for: the dollars it's worth are set aside, nothing is borrowed, and its stop is in place from the moment it fills. Each one still needs your approval.

## Why a short is riskier than a buy

- **No ceiling.** A price can only fall to zero, but it can keep rising. On a short, the stop is what limits the loss.
- **Gaps.** Over a weekend or on news, a price can jump past the stop, which then fills at the first price available ([Stop orders](#/learn/stop-orders)).
- **Financing.** A short still open at 5 pm ET is charged or paid the interest gap between its two currencies, like a long ([How trading forex differs](#/learn/forex-trading-differs)). Selling the currency with the higher interest rate usually costs you every night.

## Why the stock and crypto books don't short

A short sale of a stock sells shares you don't own, which you borrow for delivery ([Investor.gov](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-51)). At Alpaca that needs margin and at least $2,000 of equity ([Alpaca](https://docs.alpaca.markets/us/v1.4.2/docs/margin-and-short-selling)), and the loss keeps growing for as long as the price rises. Crypto can't be sold short at Alpaca at all ([Alpaca](https://alpaca.markets/support/can-i-use-margin-to-trade-crypto-can-i-short-it)). So in this app only the forex book sells short.

## Before real money

The backtests and gates you ran so far only bought. With short selling on, run Gate 1 again: `trader --env-file ../.env.forex gate1`. Backtests and gates use the choices you made on the dashboard, so they test what the book will actually trade.
