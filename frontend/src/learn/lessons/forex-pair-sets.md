# Standard or exotic pairs

Under **Your settings** on the Forex tab you pick one of two sets of pairs. The book trades one set at a time. Every pair has the US dollar on one side, so each size, stop and loss is counted in dollars.

## Standard: the seven majors

EUR/USD, GBP/USD, USD/JPY, USD/CHF, USD/CAD, AUD/USD and NZD/USD: the dollar against the euro, the pound, the yen, the Swiss franc, and the Canadian, Australian and New Zealand dollars. These are the most traded pairs, with the tightest spreads ([FXStreet](https://www.fxstreet.com/amp/education/currency-pairs-explained-majors-minors-and-exotics-202512282315)).

| Setting | Standard |
| --- | --- |
| Recommended stop | 3% from the entry |
| Most per pair | 14% of the account, seven pairs at most |
| A full stop-out costs | about 0.42% of the account |
| Backtest costs | 0.03% per side, plus 2.5% a year of financing |

## Exotic: the dollar against six emerging-market currencies

USD/MXN, USD/ZAR, USD/PLN, USD/HUF, USD/CZK and USD/SGD: the Mexican peso, the South African rand, the Polish zloty, the Hungarian forint, the Czech koruna and the Singapore dollar.

These currencies trade less, so spreads are wider, and their prices react to local news such as an election or a central bank surprise ([FxPro](https://fxpro.com/help-section/education/beginners/articles/exploring-exotic-currency-pairs)). Most swing more than the majors: over roughly 2021 to 2023, USD/ZAR moved about 12.9% a year and USD/MXN 9.2%, against 6.6% for EUR/USD. The Singapore dollar is the calm one, at 3.9% ([tastyfx](https://tastyfx.com/news/10-most-volatile-forex-pairs-to-trade-231212)).

So this set allows for more:

| Setting | Exotic |
| --- | --- |
| Recommended stop | 5% from the entry, so ordinary swings don't knock you out |
| Most per pair | 10% of the account, six pairs at most |
| A full stop-out costs | about 0.5% of the account |
| Backtest costs | 0.15% per side, plus 6% a year of financing |

Your OANDA account has to offer these pairs. If it doesn't offer one, OANDA refuses its orders and the dashboard shows the refusal.

## Pairs with the dollar first

In USD/MXN the dollar comes first: the price is pesos per dollar, and one unit is one dollar. So 10,000 units is a $10,000 position. Its profit arrives in pesos, and the app counts it back into dollars at the current price. USD/JPY, USD/CHF and USD/CAD in the standard set work the same way.

Buying USD/MXN bets on the dollar rising against the peso. With short selling on, selling it bets on the peso ([Selling short](#/learn/forex-short-selling)).

## Why the Turkish lira is left out

Financing follows the gap between the two currencies' interest rates ([How trading forex differs](#/learn/forex-trading-differs)). In October 2026 Turkey's central bank cut its policy rate to 36% ([Trading Economics](https://tradingeconomics.com/turkey/interest-rate/news/594222)), while the Fed held its target range at 3.75% to 4% ([Federal Reserve](https://www.federalreserve.gov/monetarypolicy/files/monetary20261028a1.pdf)). Holding the dollar against the lira would cost roughly that 32-point gap a year, plus the dealer's fee. Meanwhile the lira kept sliding, to a record low near 50 per dollar in November 2026 ([Trading Economics](https://tradingeconomics.com/turkey/currency/news/597666)), so the trend rule would sit on the dollar's side, paying that cost, nearly all the time.

## Switching sets

Pick a set and save; the exotic set shows its warnings first. The book won't switch while it still holds pairs that aren't in the new set, because it only manages the pairs of the set you pick: close those positions first. Your backtests ran on the other pairs, so run Gate 1 again before you trade real money with the new set.
