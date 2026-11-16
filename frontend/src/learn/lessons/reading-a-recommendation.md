# Reading a recommendation

Every evening the app makes a call on each symbol in the strategy.

| Call | What it means | What you do |
| --- | --- | --- |
| Buy | The rule says own it, and you don't yet | Approve or reject the order |
| Sell | You own it, and the rule says exit | Approve or reject the order |
| Hold | You own it, and the rule still says own it | Nothing |
| Stay out | You don't own it, and the rule says not to | Nothing |

## The numbers on a Buy

- **Limit:** the most the order will pay per share ([limit orders](#/learn/market-and-limit-orders)).
- **Stop:** where the protective stop will sit, 8% below the limit ([stops](#/learn/stop-orders)).
- **Cost:** shares times the limit, sized by the 1% rule ([sizing](#/learn/position-sizing)).
- **At risk:** what you'd lose if the stop is hit at its price. A gap can make the real loss bigger.
- **Reason:** the rule's own words, such as how far the price sits above its average.

When a Buy comes without an order, the card says why: no cash left, every position slot full, or one share costing more than the position may use.

## The track record

Each rule's record sits above its calls: how it did in its backtest (how many trades won, the average win and loss), whether it has passed Gate 1, and how this account has done since it started. A rule that hasn't passed Gate 1 is still an experiment, and its calls deserve less trust.

## Scanner ideas are different

The scanner ranks a watchlist you choose the way the momentum rule would. Its ideas are labeled untested until a strategy covering that list passes Gate 1, and they can't be approved as orders. Treat them as homework: to test the list, set it as the strategy's universe and run Gate 1.

## Before you approve

1. Read the reason. Does it match the rule?
2. Check the dollars at risk. Could you live with losing them?
3. Look at the record. Has the rule passed its gates?
