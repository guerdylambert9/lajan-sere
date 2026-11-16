// The Learn section: modules, lessons, quizzes and the glossary.
// Lesson text lives in ./lessons/*.md so it's easy to edit; links between lessons use #/learn/<id>.

import backtests from "./lessons/backtests.md?raw";
import cryptoRiskAndSizing from "./lessons/crypto-risk-and-sizing.md?raw";
import cryptoTaxes from "./lessons/crypto-taxes.md?raw";
import cryptoTradingDiffers from "./lessons/crypto-trading-differs.md?raw";
import drawdowns from "./lessons/drawdowns.md?raw";
import forexLeverageAndSizing from "./lessons/forex-leverage-and-sizing.md?raw";
import forexPairSets from "./lessons/forex-pair-sets.md?raw";
import forexShortSelling from "./lessons/forex-short-selling.md?raw";
import forexTaxes from "./lessons/forex-taxes.md?raw";
import forexTradingDiffers from "./lessons/forex-trading-differs.md?raw";
import limitsAndDiversification from "./lessons/limits-and-diversification.md?raw";
import marketAndLimitOrders from "./lessons/market-and-limit-orders.md?raw";
import momentum from "./lessons/momentum.md?raw";
import paperAndLive from "./lessons/paper-and-live.md?raw";
import positionSizing from "./lessons/position-sizing.md?raw";
import readingARecommendation from "./lessons/reading-a-recommendation.md?raw";
import stocksEtfsAndTheTradingDay from "./lessons/stocks-etfs-and-the-trading-day.md?raw";
import stopOrders from "./lessons/stop-orders.md?raw";
import taxesAndRecords from "./lessons/taxes-and-records.md?raw";
import theGates from "./lessons/the-gates.md?raw";
import trendFollowing from "./lessons/trend-following.md?raw";
import whatCryptoIs from "./lessons/what-crypto-is.md?raw";
import whatForexIs from "./lessons/what-forex-is.md?raw";
import whatThisAppDoes from "./lessons/what-this-app-does.md?raw";

export interface Lesson {
  id: string;
  title: string;
  minutes: number;
  body: string;
}

export interface Question {
  prompt: string;
  options: string[];
  answer: number; // index into options
  explain: string;
}

export interface Module {
  id: string;
  title: string;
  summary: string;
  lessons: Lesson[];
  quiz: Question[];
}

export interface GlossaryEntry {
  term: string;
  definition: string;
  lesson?: string;
}

export const MODULES: Module[] = [
  {
    id: "start",
    title: "Start here",
    summary: "What the app does, what it trades, and why you practice on paper first.",
    lessons: [
      { id: "what-this-app-does", title: "What this app does (and doesn't)", minutes: 3, body: whatThisAppDoes },
      { id: "stocks-etfs-and-the-trading-day", title: "Stocks, ETFs and the trading day", minutes: 4, body: stocksEtfsAndTheTradingDay },
      { id: "paper-and-live", title: "Paper money and real money", minutes: 3, body: paperAndLive },
    ],
    quiz: [
      {
        prompt: "When does the app decide its calls each day?",
        options: ["At the opening bell", "Every hour", "After the close, from closing prices", "Whenever you open the dashboard"],
        answer: 2,
        explain: "The signals job runs at 5:15 pm New York time on the day's closes; approved orders go out at 9:50 am the next trading day.",
      },
      {
        prompt: "What is an ETF?",
        options: ["One company's shares", "A basket of many securities that trades like one stock", "A kind of order", "A government bond"],
        answer: 1,
        explain: "An exchange-traded fund holds many stocks or bonds, which is why one ETF spreads your money widely.",
      },
      {
        prompt: "Why practice on paper first?",
        options: [
          "Paper profits can be withdrawn",
          "Paper fills are always worse, so it's a tougher test",
          "Mistakes cost nothing while you learn how the rules behave",
          "The gates skip paper trading",
        ],
        answer: 2,
        explain: "Paper uses real prices and pretend money, so bugs and bad habits show up before any money is at stake.",
      },
      {
        prompt: "By default, what does an order need before the app sends it?",
        options: ["An AI rating", "Your approval", "Nothing", "A phone call from the broker"],
        answer: 1,
        explain: "Every order waits for your approval unless you turn on AUTO_APPROVE, and it still passes the risk checks.",
      },
    ],
  },
  {
    id: "orders",
    title: "Orders",
    summary: "How market, limit and stop orders work, and why a stop can sell below its price.",
    lessons: [
      { id: "market-and-limit-orders", title: "Market and limit orders", minutes: 4, body: marketAndLimitOrders },
      { id: "stop-orders", title: "Stops, gaps and one-triggers-other orders", minutes: 4, body: stopOrders },
    ],
    quiz: [
      {
        prompt: "A buy limit order at $50.00. Which fill price is possible?",
        options: ["$50.10", "$49.80", "Any price", "Only the day's closing price"],
        answer: 1,
        explain: "A buy limit fills only at the limit or lower, so $49.80 is possible and $50.10 is not.",
      },
      {
        prompt: "A stop sits at $90. The stock closes at $93, then opens at $84 after bad news. What most likely happens?",
        options: ["It sells near $84", "It sells at exactly $90", "It doesn't sell", "It sells at $93"],
        answer: 0,
        explain: "A stop is a trigger, not a price promise. It becomes a market order and sells at the next available price after the gap.",
      },
      {
        prompt: "Why does every buy go out as a one-triggers-other order?",
        options: [
          "So it fills faster",
          "So the protective stop goes live at the broker the moment the buy fills",
          "To get a lower price",
          "To avoid taxes",
        ],
        answer: 1,
        explain: "The stop lives at the broker from the first moment, so it protects the position even when this app is off.",
      },
      {
        prompt: "What does a market order give up?",
        options: ["Control over the price", "The chance of filling", "The stop", "Nothing"],
        answer: 0,
        explain: "A market order almost always fills, but at whatever the best available price is at that moment.",
      },
    ],
  },
  {
    id: "risk",
    title: "Risk",
    summary: "Position sizing, the math of losses, and the limits that keep one mistake small.",
    lessons: [
      { id: "position-sizing", title: "Sizing a trade with the 1% rule", minutes: 4, body: positionSizing },
      { id: "drawdowns", title: "Drawdowns and the math of losses", minutes: 3, body: drawdowns },
      { id: "limits-and-diversification", title: "Diversification and the app's limits", minutes: 4, body: limitsAndDiversification },
    ],
    quiz: [
      {
        prompt: "Your equity is $50,000 and the risk per trade is 1%. What's the most you plan to lose on one trade?",
        options: ["$50", "$500", "$1,000", "$5,000"],
        answer: 1,
        explain: "1% of $50,000 is $500. The app sizes positions so a stop at its price loses no more than that.",
      },
      {
        prompt: "An account falls 50%. What gain does it need to get back to even?",
        options: ["50%", "75%", "100%", "150%"],
        answer: 2,
        explain: "Half the money has to double: 1 ÷ (1 − 0.5) − 1 = 100%.",
      },
      {
        prompt: "Equity is down 2.4% today. What happens to new buys?",
        options: ["They're blocked until tomorrow", "They're doubled", "They're sent at market", "Every position is sold"],
        answer: 0,
        explain: "The daily loss limit is 2%: past it, the app makes no new buys that day. Sells still go through.",
      },
      {
        prompt: "Why mix stocks, bonds, gold and commodities?",
        options: [
          "They always go up",
          "They don't always move together, so one fall hurts less",
          "Bonds can't lose money",
          "It makes taxes simpler",
        ],
        answer: 1,
        explain: "In 2008 long-term Treasuries rose as stocks fell; in 2022 commodities rose as stocks and bonds fell.",
      },
    ],
  },
  {
    id: "strategies",
    title: "The strategies",
    summary: "Trend following and momentum: the rules, why they can work, and when they struggle.",
    lessons: [
      { id: "trend-following", title: "Trend following", minutes: 4, body: trendFollowing },
      { id: "momentum", title: "Momentum", minutes: 4, body: momentum },
      { id: "reading-a-recommendation", title: "Reading a recommendation", minutes: 4, body: readingARecommendation },
    ],
    quiz: [
      {
        prompt: "Under the trend rule, you own SPY and it closes 3% below its 200-day average. What's the call?",
        options: ["Buy more", "Hold", "Sell", "Stay out"],
        answer: 2,
        explain: "The rule owns a symbol only while it closes above its average; a held symbol below it is a Sell.",
      },
      {
        prompt: "When does the momentum rule change what it holds?",
        options: ["Every day", "On the first trading day of each month", "Only when a stop is hit", "Once a year"],
        answer: 1,
        explain: "It ranks once a month, so a call can stay Hold even when today's ranking has moved.",
      },
      {
        prompt: "When do trend rules usually struggle?",
        options: ["Long, steady rises", "Choppy, sideways markets", "Long, steady falls", "Never"],
        answer: 1,
        explain: "When prices zigzag around the average, the rule keeps buying and selling and takes many small losses.",
      },
      {
        prompt: "A scanner idea says \"Buy idea\" and \"untested\". What should you do?",
        options: [
          "Approve it right away",
          "Buy twice as much",
          "Treat it as homework: test the watchlist with Gate 1 first",
          "Ignore every idea forever",
        ],
        answer: 2,
        explain: "Ideas outside a tested strategy can't be sent as orders. Set the watchlist as the universe and run Gate 1 to test it.",
      },
    ],
  },
  {
    id: "testing",
    title: "Testing and trust",
    summary: "How backtests fool people, how the gates protect you, and the tax basics.",
    lessons: [
      { id: "backtests", title: "Backtests and their traps", minutes: 4, body: backtests },
      { id: "the-gates", title: "From paper to live: the gates", minutes: 3, body: theGates },
      { id: "taxes-and-records", title: "Taxes and records in the US", minutes: 4, body: taxesAndRecords },
    ],
    quiz: [
      {
        prompt: "You backtest today's S&P 500 members back to 2005. Which trap is that?",
        options: ["Look-ahead bias", "Survivorship bias", "Overfitting", "A wash sale"],
        answer: 1,
        explain: "Companies that failed or were dropped since 2005 aren't on today's list, so the test only sees survivors.",
      },
      {
        prompt: "Why keep 2023 to today unseen while you develop a rule?",
        options: [
          "To save disk space",
          "So Gate 1 tests the rule on years it wasn't tuned to",
          "Because that data is missing",
          "To pay less tax",
        ],
        answer: 1,
        explain: "Held-out years are a fair test only if you don't tune on them; the app logs every look.",
      },
      {
        prompt: "You sell an ETF at a loss and buy it back 10 days later. What can happen?",
        options: [
          "The loss doubles",
          "It's a wash sale: the loss can't be deducted now and is added to the new shares' cost",
          "Nothing",
          "The account is closed",
        ],
        answer: 1,
        explain: "Buying the same or a substantially identical security within 30 days before or after a loss sale is a wash sale.",
      },
      {
        prompt: "You held shares for 8 months and sold at a gain. How is it taxed?",
        options: ["Tax-free", "As a long-term gain at 0%, 15% or 20%", "As a short-term gain, at ordinary income rates", "As a wash sale"],
        answer: 2,
        explain: "One year or less is short-term, taxed like ordinary income.",
      },
    ],
  },
  {
    id: "crypto",
    title: "Crypto",
    summary: "What a coin is, how the crypto book trades it around the clock, how far it can fall, and how it's taxed.",
    lessons: [
      { id: "what-crypto-is", title: "What crypto is, and what you'd own", minutes: 4, body: whatCryptoIs },
      { id: "crypto-trading-differs", title: "How trading crypto differs", minutes: 5, body: cryptoTradingDiffers },
      { id: "crypto-risk-and-sizing", title: "Crypto risk and position size", minutes: 4, body: cryptoRiskAndSizing },
      { id: "crypto-taxes", title: "Crypto taxes in the US", minutes: 4, body: cryptoTaxes },
    ],
    quiz: [
      {
        prompt: "When does the crypto book make its daily calls?",
        options: [
          "At 4:00 pm ET, like stocks",
          "Just after midnight Chicago time, when Alpaca's crypto day ends",
          "Every hour",
          "Whenever the price moves 5%",
        ],
        answer: 1,
        explain: "Crypto never closes, so the app uses Alpaca's daily bars, which end at midnight Chicago time (1:00 am New York time).",
      },
      {
        prompt: "You buy 0.1 BTC as a taker on Alpaca's lowest fee tier. What lands in your account?",
        options: [
          "0.1 BTC, with the fee charged in cash",
          "About 0.09975 BTC: the 0.25% fee comes out of the coins",
          "0.1025 BTC",
          "0.1 BTC: crypto trades are free",
        ],
        answer: 1,
        explain: "Alpaca takes the crypto fee from the asset you receive, so a buy credits slightly fewer coins.",
      },
      {
        prompt: "Bitcoin falls straight through your stop-limit's limit price. What happens?",
        options: [
          "It sells at the stop price anyway",
          "It may not fill, so you still hold the coins; the app warns you and you decide",
          "The broker sells at any price",
          "The app buys more",
        ],
        answer: 1,
        explain: "A stop-limit never sells below its limit. That protects the price but not the exit.",
      },
      {
        prompt: "Why does each coin get only about 5% of the account?",
        options: [
          "It's Alpaca's limit",
          "A worst-case fill is about 19% below the buy, and one trade may lose at most 1% of the account",
          "Coins are too expensive to buy more",
          "Taxes are higher on crypto",
        ],
        answer: 1,
        explain: "1% ÷ 19.25% ≈ 5.2%, and the crypto book caps each coin at 5%.",
      },
      {
        prompt: "You sell a spot bitcoin ETF at a loss and buy it back two weeks later. What should you assume?",
        options: [
          "The wash sale rule never touches anything crypto",
          "The wash sale rule applies: ETF shares are securities",
          "The loss is doubled",
          "It only matters for ether",
        ],
        answer: 1,
        explain: "Coins themselves are taxed as property, but ETF shares are securities, so plan as if the rule applies.",
      },
    ],
  },
  {
    id: "forex",
    title: "Forex",
    summary:
      "What a currency pair is, how the forex book trades from Sunday to Friday, why it borrows nothing, standard or exotic pairs, selling short, and how it's taxed.",
    lessons: [
      { id: "what-forex-is", title: "What forex is: pairs, pips and the dollar", minutes: 4, body: whatForexIs },
      { id: "forex-trading-differs", title: "How trading forex differs", minutes: 5, body: forexTradingDiffers },
      { id: "forex-leverage-and-sizing", title: "Leverage, and why this book uses none", minutes: 4, body: forexLeverageAndSizing },
      { id: "forex-pair-sets", title: "Standard or exotic pairs", minutes: 4, body: forexPairSets },
      { id: "forex-short-selling", title: "Selling short: betting on a pair falling", minutes: 4, body: forexShortSelling },
      { id: "forex-taxes", title: "Forex taxes in the US", minutes: 3, body: forexTaxes },
    ],
    quiz: [
      {
        prompt: "It's Tuesday at 10:00 am ET. Which close is the forex book's newest daily bar?",
        options: [
          "Today's 4:00 pm close",
          "Monday's 5:00 pm ET close",
          "Midnight in Chicago",
          "Whatever traded a minute ago",
        ],
        answer: 1,
        explain: "The forex day ends at 5 pm New York time, so until 5 pm Tuesday the newest finished day is Monday's.",
      },
      {
        prompt: "At 50:1 leverage, how far does EUR/USD have to move against you to wipe out the deposit?",
        options: ["50%", "10%", "2%", "It can't: forex deposits are protected"],
        answer: 2,
        explain: "50 × 2% = 100%. That's why the forex book borrows nothing.",
      },
      {
        prompt: "With $100,000 on the standard pairs, about how much does one position start at, and what does a full stop-out cost?",
        options: [
          "$100,000, losing 3%",
          "About $14,000, losing about 0.42% of the account",
          "About $33,000, losing exactly 1%",
          "$5,000, like a coin",
        ],
        answer: 1,
        explain: "Risk alone would allow a third (1% ÷ 3%), but each pair is capped at 14% so seven fit in the account; a 3% stop costs about 0.42%.",
      },
      {
        prompt: "Short selling is on and the book sells EUR/USD short at 1.1000. Where does its stop go, and what hurts the trade?",
        options: [
          "3% below, at about 1.067; a falling euro hurts it",
          "3% above, at about 1.133; a rising euro hurts it",
          "There's no stop on a short",
          "At 1.1000, so it can't lose",
        ],
        answer: 1,
        explain: "A short gains when the pair falls and loses when it rises, so its stop sits above the entry.",
      },
      {
        prompt: "Why do the exotic pairs get a 5% stop and at most 10% of the account each?",
        options: [
          "OANDA requires it",
          "Most of those currencies swing more and cost more to trade, so a 3% stop would trip on ordinary moves",
          "Exotic pairs can't fall",
          "To pay less tax",
        ],
        answer: 1,
        explain: "The wider stop leaves room for normal swings; the smaller size keeps a stop-out near 0.5% of the account.",
      },
      {
        prompt: "Why can the app sell a forex position without canceling its stop-loss first?",
        options: [
          "US rules forbid canceling a stop",
          "The stop belongs to the trade, and OANDA cancels it when the exit closes the trade",
          "Forex stops never fill",
          "The stop is the exit order",
        ],
        answer: 1,
        explain: "The position stays protected right up to the moment the exit fills.",
      },
      {
        prompt: "You trade spot forex and never elect anything. How are your gains taxed?",
        options: [
          "60% long-term, 40% short-term",
          "As ordinary income, under Section 988",
          "Tax-free below $10,000",
          "As long-term gains if held a year",
        ],
        answer: 1,
        explain: "Section 988 is the default. The 60/40 split needs a Section 1256 election in place by January 1.",
      },
    ],
  },
];

export const LESSONS: Lesson[] = MODULES.flatMap((module) => module.lessons);

export function findLesson(id: string): { lesson: Lesson; module: Module; index: number } | null {
  const index = LESSONS.findIndex((lesson) => lesson.id === id);
  if (index < 0) return null;
  const module = MODULES.find((m) => m.lessons.some((lesson) => lesson.id === id));
  return module ? { lesson: LESSONS[index], module, index } : null;
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  "short-selling": {
    term: "Short selling",
    definition:
      "Selling first to buy back later, so the trade gains when the price falls and loses when it rises. Here only the forex book can, once you switch it on, with a stop above the entry.",
    lesson: "forex-short-selling",
  },
  "major-pair": {
    term: "Major pair",
    definition:
      "One of the seven most traded pairs: the dollar against the euro, pound, yen, Swiss franc, and the Canadian, Australian and New Zealand dollars.",
    lesson: "forex-pair-sets",
  },
  "exotic-pair": {
    term: "Exotic pair",
    definition:
      "The dollar against an emerging-market currency such as the Mexican peso or South African rand: wider spreads, bigger swings and higher financing than the majors.",
    lesson: "forex-pair-sets",
  },
  "currency-pair": {
    term: "Currency pair",
    definition: "Two currencies priced against each other. EUR/USD is the price of one euro in dollars; buying it swaps dollars for euros.",
    lesson: "what-forex-is",
  },
  pip: {
    term: "Pip",
    definition: "The usual step in a currency's price: 0.0001 for most pairs, 0.01 against the yen. On 10,000 units of EUR/USD a pip is worth $1.",
    lesson: "what-forex-is",
  },
  leverage: {
    term: "Leverage",
    definition:
      "Trading more than you deposit, with the rest lent by the dealer. US dealers may lend up to 50 times the deposit on major pairs; the forex book uses none.",
    lesson: "forex-leverage-and-sizing",
  },
  financing: {
    term: "Financing (rollover)",
    definition:
      "Interest charged or paid on a forex position still open at 5 pm ET, from the gap between the two currencies' interest rates plus the dealer's fee.",
    lesson: "forex-trading-differs",
  },
  "fifo-rule": {
    term: "FIFO and no hedging",
    definition: "US forex rules: trades in a pair close oldest first, and you can't hold a long and a short in the same pair at once.",
    lesson: "forex-trading-differs",
  },
  "section-988": {
    term: "Section 988",
    definition: "The default US tax rule for spot forex: gains and losses are ordinary income or loss, unless you elect Section 1256 by January 1.",
    lesson: "forex-taxes",
  },
  "crypto-asset": {
    term: "Crypto asset",
    definition: "A coin or token recorded on a shared public ledger, such as bitcoin or ether. No company or earnings stand behind it.",
    lesson: "what-crypto-is",
  },
  "crypto-pair": {
    term: "Trading pair",
    definition: "Two assets priced against each other. BTC/USD is bitcoin priced in US dollars.",
    lesson: "what-crypto-is",
  },
  custody: {
    term: "Custody",
    definition: "Who holds an asset for you. A broker holding your coins has custody of them; SIPC protection doesn't cover most crypto.",
    lesson: "what-crypto-is",
  },
  "form-1099-da": {
    term: "Form 1099-DA",
    definition: "The form brokers use to report your crypto sales to you and the IRS, starting with 2025 sales.",
    lesson: "crypto-taxes",
  },
  gtc: {
    term: "Good till canceled (GTC)",
    definition: "An order that stays open until it fills or you cancel it. Crypto orders here are GTC; the app cancels any that sit an hour unfilled.",
    lesson: "crypto-trading-differs",
  },
  "maker-taker": {
    term: "Maker and taker fees",
    definition:
      "A maker's order waits on the book until someone trades with it; a taker's order trades at once with one that's waiting. Alpaca's lowest crypto tier charges 0.15% and 0.25%.",
    lesson: "crypto-trading-differs",
  },
  "spot-etf": {
    term: "Spot crypto ETF",
    definition: "A fund that holds bitcoin or ether itself and trades like a stock, during market hours, in a stock account.",
    lesson: "what-crypto-is",
  },
  "stop-limit-order": {
    term: "Stop-limit order",
    definition:
      "A stop that sells only at its limit price or better. It can't fill at a terrible price, but it may not fill at all if the price falls straight through the limit. The crypto book uses these.",
    lesson: "crypto-trading-differs",
  },
  backtest: {
    term: "Backtest",
    definition: "Running a rule over past prices as if you had traded it, costs included.",
    lesson: "backtests",
  },
  benchmark: {
    term: "Benchmark",
    definition:
      "What a strategy is measured against: SPY for stocks, BTC/USD for crypto, EUR/USD for forex. If the rules can't beat simply holding it, they aren't worth it.",
    lesson: "the-gates",
  },
  cash: {
    term: "Cash",
    definition: "Money in the account that isn't invested. Sells add to it and buys use it.",
    lesson: "position-sizing",
  },
  "daily-loss-limit": {
    term: "Daily loss limit",
    definition: "If equity is down 2% on the day, the app makes no new buys until the next day. Sells still go through.",
    lesson: "drawdowns",
  },
  drawdown: {
    term: "Drawdown (below peak)",
    definition: "How far equity has fallen from its highest point, as a percentage.",
    lesson: "drawdowns",
  },
  equity: {
    term: "Equity",
    definition: "Everything the account is worth right now: cash plus the market value of every position.",
    lesson: "position-sizing",
  },
  etf: {
    term: "ETF",
    definition: "Exchange-traded fund: a basket of many stocks or bonds that trades like a single stock.",
    lesson: "stocks-etfs-and-the-trading-day",
  },
  fill: {
    term: "Fill",
    definition: "A trade actually happening. A partial fill means only some of the shares traded.",
    lesson: "market-and-limit-orders",
  },
  gap: {
    term: "Gap",
    definition: "A jump between one close and the next trade, usually overnight after news. A gap can carry a stop's sale well below its price.",
    lesson: "stop-orders",
  },
  gate: {
    term: "Gate",
    definition: "A test with a written pass mark that has to pass before the next step toward real money.",
    lesson: "the-gates",
  },
  holdout: {
    term: "Held-out years",
    definition: "Years kept unseen while you develop a rule, then used once to test it fairly.",
    lesson: "backtests",
  },
  "kill-switch": {
    term: "Kill switch",
    definition: "Cancels pending buys and blocks every new order; protective stops stay. It engages by itself at 10% below the peak.",
    lesson: "drawdowns",
  },
  "limit-order": {
    term: "Limit order",
    definition: "An order with a worst acceptable price: a buy fills at the limit or lower, a sell at the limit or higher.",
    lesson: "market-and-limit-orders",
  },
  "look-ahead-bias": {
    term: "Look-ahead bias",
    definition: "A test using information that wasn't known at the time, which makes it look better than real trading could.",
    lesson: "backtests",
  },
  "market-order": {
    term: "Market order",
    definition: "An order to trade right away at the best available price. It almost always fills, but the price isn't under your control.",
    lesson: "market-and-limit-orders",
  },
  momentum: {
    term: "Momentum",
    definition: "Owning what rose the most over the past year, because recent winners have tended to keep doing well for a while.",
    lesson: "momentum",
  },
  "momentum-return": {
    term: "Past-year return",
    definition: "The return over the 12 months before the latest month: what the momentum rule ranks by. Leaving out the latest month avoids short-term reversals.",
    lesson: "momentum",
  },
  "moving-average": {
    term: "Moving average",
    definition: "The average closing price over a set number of days, such as 200. It shows the direction of the longer trend.",
    lesson: "trend-following",
  },
  oto: {
    term: "One-triggers-other (OTO)",
    definition: "A buy that switches on its protective stop at the broker the moment it fills.",
    lesson: "stop-orders",
  },
  overfitting: {
    term: "Overfitting",
    definition: "Tuning a rule until it fits the past by luck, so it fails on new data.",
    lesson: "backtests",
  },
  "paper-trading": {
    term: "Paper trading",
    definition: "Practice trading with pretend money at real market prices.",
    lesson: "paper-and-live",
  },
  position: {
    term: "Position",
    definition: "The shares you own in one symbol.",
    lesson: "position-sizing",
  },
  proceeds: {
    term: "Proceeds",
    definition: "The cash a sale brings in: shares times the sale price.",
    lesson: "market-and-limit-orders",
  },
  "risk-per-trade": {
    term: "Risk per trade (at risk)",
    definition: "What you'd lose if a trade's stop is hit at its price: shares × (entry − stop). The app keeps it at or under 1% of equity.",
    lesson: "position-sizing",
  },
  slippage: {
    term: "Slippage",
    definition: "The difference between the price you expected and the price you got.",
    lesson: "market-and-limit-orders",
  },
  "stop-order": {
    term: "Stop order",
    definition: "An order that waits below the market and sells if the price falls to it. After a gap it can sell well below its price.",
    lesson: "stop-orders",
  },
  "survivorship-bias": {
    term: "Survivorship bias",
    definition: "Testing on a list that only includes survivors, such as today's index members, which flatters the results.",
    lesson: "backtests",
  },
  "trend-following": {
    term: "Trend following",
    definition: "Owning what trades above its long-term average and stepping aside when it falls below.",
    lesson: "trend-following",
  },
  universe: {
    term: "Universe",
    definition: "The list of symbols a strategy may trade. Here it's ten ETFs.",
    lesson: "stocks-etfs-and-the-trading-day",
  },
  "wash-sale": {
    term: "Wash sale",
    definition: "Selling at a loss and buying the same or a substantially identical security within 30 days before or after. The loss can't be deducted then.",
    lesson: "taxes-and-records",
  },
  watchlist: {
    term: "Watchlist",
    definition: "The list the scanner ranks for ideas. It starts with the 11 sector ETFs, and you can add any stocks.",
    lesson: "reading-a-recommendation",
  },
  "win-rate": {
    term: "Win rate",
    definition: "The share of closed trades that made money. Trend rules often win less than half the time and rely on wins being bigger than losses.",
    lesson: "trend-following",
  },
};
