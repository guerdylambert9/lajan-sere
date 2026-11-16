# From paper to live: the gates

A **gate** is a test with a written pass mark that you pass before each step toward real money. Each gate has a command that prints its checks and says pass or fail.

| Gate | It shows | Command |
| --- | --- | --- |
| 0 | The app can place, read back and cancel a paper order | `trader smoke-test` |
| 1 | The rule beat SPY on held-out years after costs, and survives small changes and a day's delay | `trader gate1` |
| 2 | Ten weekdays of clean broker checks on paper, and the kill switch tested | `trader gate2` |
| 3 | The optional AI layer beat the rules alone after its costs | `trader compare-ab` |
| 4 | Twelve weeks of paper results inside the backtest's ranges | `trader gate4` |
| 5 | Three live months tracking paper before you add money | `trader gate5` |

**SPY** is the benchmark: if a rule can't beat simply holding the S&P 500, it isn't worth the effort.

The crypto book (Phase 6) passes the same gates again, in its own paper account, measured against simply holding bitcoin ([Crypto risk](#/learn/crypto-risk-and-sizing)). The forex book (Phase 7) does the same in an OANDA practice account, measured against holding EUR/USD, or USD/MXN with the exotic pairs ([Leverage, and why this book uses none](#/learn/forex-leverage-and-sizing)).

A gate tests one exact set of rules. If you change a book's stop, its pairs or short selling under **Your settings**, run Gate 1 again before you trade real money with the change; backtests and gates read those choices too.

## Three habits

1. Decide the pass mark before you look.
2. Never loosen a gate you just failed. Change the idea or fix the app, then try again.
3. Keep the reports in `backend/reports/`. They're your record of why you moved forward.

## Going live

Live trading needs three deliberate settings, and it should start with an amount you can afford to lose. Keep a paper account running the same rules alongside, so Gate 5 can compare the two before you add money.
