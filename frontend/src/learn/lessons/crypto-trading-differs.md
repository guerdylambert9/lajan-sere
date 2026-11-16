# How trading crypto differs

Same rules, same risk checks, same approvals. What changes is the clock, the costs and the kind of stop.

## It never closes

Crypto trades 24 hours a day, every day ([Alpaca](https://docs.alpaca.markets/docs/crypto-trading)). The app still works from daily closes. Alpaca's crypto day ends at midnight Chicago time, so the crypto book:

1. At 1:15 am New York time, reads the day that just ended and makes its calls.
2. Waits for you to approve. Approved orders go out within 5 minutes, at any hour.
3. Puts a stop under each new position as soon as the buy fills.
4. Cancels any order that sat unfilled for an hour, so a stale price never fills by surprise.

## Fees come out of what you receive

Stock trades at Alpaca carry no commission; crypto trades pay a fee. On the lowest tier it's 0.15% when your order rests on the book (a **maker**) and 0.25% when it trades against one that's waiting (a **taker**). The fee is taken from the asset you receive ([Alpaca](https://docs.alpaca.markets/docs/crypto-fees)).

Buy 0.0841 BTC as a taker and about 0.0839 BTC lands in the account. Sell, and the fee comes out of the dollars. The app sizes each stop from the coins you actually hold, and its backtests charge 0.35% each way: the fee plus the spread.

## Stop-limits instead of plain stops

Alpaca's crypto desk takes market, limit and **stop-limit** orders, good till canceled or immediate-or-cancel, and it doesn't take one-triggers-other orders ([Alpaca](https://docs.alpaca.markets/docs/crypto-trading)). So a crypto buy can't carry its stop the way a stock buy does ([Stops](#/learn/stop-orders)). The app places the stop itself right after the fill, and checks every 5 minutes that each position has one.

A stop-limit has two prices. Take a buy at $59,435.70:

- **Stop: $50,520.35**, 15% lower. When the price reaches it, the order wakes up.
- **Limit: $47,994.33**, 5% below the stop. The order sells at this price or better, never lower.

The limit protects you from a terrible fill in a sudden plunge, but it cuts both ways: if the price falls straight through $47,994.33, the order doesn't fill and you still hold the coins ([Investor.gov](https://www.investor.gov/additional-resources/news-alerts/alerts-bulletins/investor-bulletin-stop-stop-limit-trailing-stop)). When that happens the app sends you a warning, and you decide whether to sell.

## Smaller rules worth knowing

- **Slices.** Each pair has a smallest order and a quantity step. The app reads them from Alpaca and rounds down to fit.
- **No borrowing.** There's no margin and no short selling in crypto at Alpaca. The app never uses either anyway.
- **Not every state.** Alpaca offers crypto only in some US states, and the list changes ([Alpaca](https://alpaca.markets/support/what-regions-support-cryptocurrency-trading)). Check yours before you plan on it; if it isn't there, spot crypto ETFs trade in the stock account ([What crypto is](#/learn/what-crypto-is)).
