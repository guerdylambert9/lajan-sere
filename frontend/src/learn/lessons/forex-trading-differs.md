# How trading forex differs

Stocks trade in one session a day. Currencies trade around the clock from Sunday evening to Friday evening, and the day ends at 5 pm New York time. Most of what's different about the forex book follows from that.

## The forex week and day

OANDA's market runs from about 5 pm Sunday to 5 pm Friday, New York time ([OANDA](https://www.oanda.com/assets/documents/252/Hours_of_Operation.pdf)). Each forex day closes at 5 pm New York, so the app's daily bar for Monday is the 24 hours that end Monday at 5 pm. The book's clock:

| New York time | What happens |
| --- | --- |
| 9:50 am, weekdays | Approved orders go out |
| 5:05 pm | Check against the broker; record the day's equity; cancel orders that didn't fill |
| 5:15 pm | The day's signals and proposals |

## Why 9:50 in the morning

The London and New York sessions usually overlap from 8 am to noon Eastern time ([BabyPips](https://www.babypips.com/learn/forex/market-hours)), when both financial centers are trading. Orders go out inside that window.

The hour after the 5 pm close is the opposite. Banks roll their books to the next day, liquidity thins and quotes widen; CME even pauses its currency futures for that hour ([CME Group](https://www.cmegroup.com/articles/2026/when-fx-futures-pause.html)). The app won't send orders between 4:45 and 5:15 pm ET.

## The costs: spread and financing

The main trading cost is the **spread**, the gap between the price you can buy at and the price you can sell at. Backtests charge 3 basis points (0.03%) each way on the standard pairs and 15 (0.15%) on the exotic ones ([Standard or exotic pairs](#/learn/forex-pair-sets)).

The second cost is **financing**. A position still open at 5 pm ET is charged or credited for the night. The amount reflects the gap between the two currencies' interest rates plus the dealer's fee ([OANDA](https://oanda.com/us-en/trading/financing-fees)). OANDA's own example: holding 100,000 EUR/USD at a −3% long rate costs about $9.52 a night. Weekends count too; dealers book them in one go, usually by tripling the Wednesday charge ([FOREX.com](https://www.forex.com/en-sg/glossary/rollover/)). It can be a credit when the currency you hold pays more interest, but the backtests assume a yearly charge on what's held, long or short (2.5% on the standard pairs, 6% on the exotic ones), to stay on the cautious side.

## Orders: the stop rides along

An entry is a limit order that carries its own **stop-loss**: a buy with its stop below, or, once you switch on short selling, a sell with its stop above ([Selling short](#/learn/forex-short-selling)). When it fills, OANDA attaches the stop to the new trade, the way a stock entry carries its stop. An exit can only shrink a position, never open one on the other side. When it closes the trade, OANDA cancels the trade's stop, so the stop stays in place until the moment the exit fills.

US rules add two more: trades in a pair close oldest first (FIFO), and you can't hold a long and a short in the same pair at once ([OANDA](https://www.oanda.com/us-en/trade-tap-blog/trading-knowledge/the-nfas-fifo-rule-challenges-solutions-forex-expert-advisors)). The book holds one trade per pair, long or short, and closes a long before it opens a short, so neither rule gets in its way.

## Weekend gaps

The market is shut from Friday 5 pm to Sunday 5 pm, but the news isn't. Monday can open well away from Friday's close ([Investing.com](https://investing.com/brokers/guides/forex/can-you-trade-forex-7-days-a-week)). A stop doesn't guarantee its price: if the open is below it, it sells at the first price available, which can be lower ([Stop orders](#/learn/stop-orders)).
