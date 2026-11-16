# Market and limit orders

An **order** is an instruction to buy or sell. The two basic kinds trade off price against certainty ([Investor.gov](https://www.investor.gov/introduction-investing/investing-basics/how-stock-markets-work/types-orders)).

- A **market order** buys or sells right away at the best price available. It almost always fills, but you don't control the price.
- A **limit order** sets the worst price you'll accept. A buy limit fills only at the limit or lower; a sell limit only at the limit or higher. You control the price, but the order may not fill.

## What the app sends

Every order here is a limit order. At 9:50 am the app re-prices each approved order at the latest trade and sets the limit 0.2% beyond it: above for a buy, below for a sell. That fills in normal trading but not after a sudden jump.

Say SPY closed at $600.00 last night:

- At 9:50 am it trades at $601.00. The buy limit becomes $602.21 (0.2% higher, rounded up to the cent), so the order pays $602.21 at most.
- If SPY has already jumped more than 2% above last night's close, the app skips the buy rather than chase it.
- If the buy hasn't filled by the close, the afternoon broker check cancels it.

## Words you'll see

- **Fill:** the trade actually happening. A **partial fill** means only some of the shares traded.
- **Slippage:** the gap between the price you expected and the price you got.
- **Day** and **GTC** (good till canceled): how long an order stays open. Entries go out as GTC so their protective stop lasts beyond the first day ([stops](#/learn/stop-orders)).
