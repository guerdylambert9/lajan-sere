# Sizing a trade with the 1% rule

Before deciding how many shares to buy, decide how much you're willing to lose if the trade goes wrong. That amount is the **risk per trade**, and this app keeps it at or under 1% of your equity. **Equity** is everything the account is worth: cash plus the value of every position.

## The arithmetic

Risk per trade = shares × (entry price − stop price)

With the stop 8% below the entry, a position can be up to 1% ÷ 8% = 12.5% of equity before hitting its stop would cost more than 1%. The app also caps any new position at 10% of equity, so 10% is the size it uses.

An example with $100,000 of equity:

| Step | Number |
| --- | ---: |
| Position size: 10% of equity | $10,000 |
| Entry price | $500.00 |
| Shares: $10,000 ÷ $500 | 20 |
| Stop: 8% below the entry | $460.00 |
| Loss if the stop is hit: 20 × $40 | $800, or 0.8% of equity |

## Why sizing matters more than picking

A run of losses is normal, even for rules that work. Lose 1% ten times in a row and the account is down about 9.6%. Lose 10% ten times in a row and it's down about 65%. The first is a bad month; the second is hard to come back from ([drawdowns](#/learn/drawdowns)).

## Small accounts

The app buys whole shares. If one share costs more than the position may use, it skips that buy and the card says why. With $5,000 of equity, for example, 10% is $500, which won't buy one share of a $600 ETF.
