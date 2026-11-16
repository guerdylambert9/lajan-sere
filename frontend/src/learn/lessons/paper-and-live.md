# Paper money and real money

**Paper trading** is practice with pretend money at real market prices. Alpaca gives you paper accounts next to your real one, so orders, fills and positions behave much like the real thing while nothing is at stake.

## Why start on paper

- You find bugs and bad habits while mistakes cost nothing.
- You see how the rules feel day to day: the quiet weeks, the losing streaks, the stops.
- The gates need weeks of paper results before any real money goes in ([the gates](#/learn/the-gates)).

## Where paper differs from real money

- **Fills can be kinder.** A paper order may fill at a price a real order wouldn't get, especially in a fast market.
- **Losses don't sting.** Losing pretend money feels nothing like losing your own. Notice how you react to a losing week on paper; real money makes it harder.
- **Records stay apart.** The app keeps one database per account, so demo, paper and live results never mix.

## The three modes

| Mode | Broker | Money |
| --- | --- | --- |
| Demo | A fake broker inside the app, on made-up prices | None |
| Paper | Your Alpaca paper account (OANDA practice for forex) | Pretend money at real prices |
| Live | Your Alpaca live account (OANDA live for forex) | Real money |

The band across the top of the dashboard shows the mode. In live mode it turns into hazard stripes, and the app only goes live when three settings say so on purpose.

## Trading real money through the app

Yes, the app trades real money, the same way it trades paper. Once a book has passed Gates 0 to 4 on paper, give it a live settings file with three deliberate lines: the real broker (`BROKER=alpaca`, or `BROKER=oanda` for forex), `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true`, plus the live account's own keys and its own database. Then run the dashboard with that file. Every order still waits for your approval, the risk checks and the kill switch work as before, and after three months Gate 5 compares live with paper before you add money ([the gates](#/learn/the-gates)).

There's deliberately no switch on the dashboard for this: going live is a change you make on purpose, in a file, not a button you can press by mistake.
