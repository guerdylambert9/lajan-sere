# Drawdowns and the math of losses

A **drawdown** is how far your account has fallen from its highest point, as a percentage. On the dashboard it's called "Below peak".

## Losses need bigger gains to recover

| Loss | Gain needed to get back to even |
| --- | ---: |
| 10% | 11.1% |
| 20% | 25% |
| 33.3% | 50% |
| 50% | 100% |
| 75% | 300% |

The gain needed is 1 ÷ (1 − loss) − 1. A $10,000 account that falls 50% to $5,000 has to double to get back. That's why the app protects the downside first.

## The app's brakes

- **Daily loss limit.** If equity is down 2% on the day, the app makes no new buys until the next day. Sells still go through.
- **Kill switch at 10% below the peak.** The afternoon broker check engages it on its own. It cancels pending buys and blocks new orders, while protective stops stay in place. You find out what happened before you release it.

## Drawdowns are normal

Every strategy has them. What matters is how deep they go, how long they last, and whether they match what the backtest showed. Gate 1 rejects a strategy whose held-out years fell more than 25% below their peak, and Gate 4 checks that paper drawdowns stay within the backtest's range ([the gates](#/learn/the-gates)).
