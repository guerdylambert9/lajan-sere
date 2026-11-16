# What this app does (and doesn't)

This app turns a few simple, tested rules into trade recommendations, checks every order against hard limits, and waits for you to approve it. It doesn't predict the market, and it can lose money.

## A day in the app

1. After the market closes, at 5:15 pm New York time, the app reads the day's closing prices.
2. The strategy's rule decides what to own. Each symbol gets a call: Buy, Sell, Hold or Stay out.
3. Buys and sells become orders that wait for you. You approve or reject each one.
4. At 9:50 am the next trading day, approved orders go to the broker after a fresh price check and the risk checks again.
5. At 4:30 pm, the app checks its records against the broker's.

The crypto book, which comes later, keeps its own clock because crypto never closes ([How trading crypto differs](#/learn/crypto-trading-differs)). So does the forex book, whose day ends at 5 pm New York time ([How trading forex differs](#/learn/forex-trading-differs)).

## What it won't do

- **Guess.** Every call comes from a written rule. Ideas that no tested rule covers are labeled untested and can't be sent.
- **Trade without you.** Unless you turn on auto-approve, nothing is sent until you approve it.
- **Promise a profit.** Rules that worked in the past can stop working. Each call shows its rule's record so you can judge it.

## Why rules instead of hunches

Trading often is hard to win at. In a study of every day trader in Taiwan from 1992 to 2006, day traders as a group lost money after fees in every single year ([Barber et al.](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/day%20trading%20and%20learning%20110217.pdf)).

The rules here trade slowly, hold for days to weeks, keep each loss small, and get tested before real money is involved. That doesn't guarantee a profit, but it avoids the most common ways to lose.

> These lessons teach; they aren't investment advice. You decide what to trade.
