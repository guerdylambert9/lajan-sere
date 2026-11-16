# Diversification and the app's limits

**Diversification** means spreading money across things that don't all move together, so one bad bet can't sink the account. The strategy's ten ETFs mix US and foreign stocks, Treasury bonds, gold, commodities and real estate on purpose.

They don't always move together. In 2008, long-term Treasury bonds rose while stocks fell hard. In 2022, stocks and bonds both fell while commodities rose. No mix protects you every year, but a mix makes it less likely that everything falls at once.

## The limits in one place

| Limit | Default | What it prevents |
| --- | --- | --- |
| Risk per trade | 1% of equity | One trade hurting too much |
| Stop | 8% below the entry | A loss running on |
| Largest new position | 10% of equity | A big bet on one name |
| Open positions | 8 at most | Too many positions to follow |
| Orders per day | 10 | A bug sending a flood of orders |
| Daily loss | Down 2%: no new buys today | Chasing losses |
| Drawdown | 10% below the peak: kill switch | A bad run turning into a disaster |
| Trading window | Not in the first or last 15 minutes | The jumpiest minutes |
| Gap guard | Skip a buy that rose 2% above its close | Chasing a jump |

Every order is checked against these when it's proposed and again right before it's sent.

The numbers live in the settings file, `.env`. Tighten them whenever you like, but loosen them only after the gates show the rules work.
