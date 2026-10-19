const express = require('express');
const http = require('http');
const crypto = require('crypto');
const path = require('path');
const { Server } = require('socket.io');
const Database = require('better-sqlite3');

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: "*" } });

const PORT = 3000;
const OWNER_KEY = process.env.OWNER_KEY || "change-me-owner-key";
const START_BALANCE = 100;
const TICK_RATE = 100;
const PREPARATION_TIME = 5000;

/* ---------- DATABASE (SQLite file: aviator.db) ---------- */
const db = new Database(path.join(__dirname, 'aviator.db'));
db.pragma('journal_mode = WAL');
db.exec(`
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        balance REAL NOT NULL,
        joined TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        pod TEXT NOT NULL,
        stake REAL NOT NULL,
        won INTEGER NOT NULL,
        multiplier REAL NOT NULL,
        payout REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_after REAL NOT NULL,
        created_at TEXT NOT NULL
    );
`);

const q = {
    findUserByName: db.prepare('SELECT * FROM users WHERE username = ?'),
    findUserById: db.prepare('SELECT id, username, balance, joined FROM users WHERE id = ?'),
    insertUser: db.prepare('INSERT INTO users (username, password_hash, salt, balance, joined) VALUES (?, ?, ?, ?, ?)'),
    setBalance: db.prepare('UPDATE users SET balance = ? WHERE id = ?'),
    insertBet: db.prepare('INSERT INTO bets (user_id, pod, stake, won, multiplier, payout, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)'),
    betsForUser: db.prepare('SELECT pod, stake, won, multiplier, payout, created_at FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 200'),
    insertTxn: db.prepare('INSERT INTO transactions (user_id, type, amount, balance_after, created_at) VALUES (?, ?, ?, ?, ?)'),
    txnsForUser: db.prepare('SELECT type, amount, balance_after, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 100')
};

/* ---------- PASSWORDS AND SESSIONS ---------- */
function round2(n) {
    return Math.round(n * 100) / 100;
}

function hashPassword(password, salt) {
    return crypto.scryptSync(password, salt, 64).toString('hex');
}

function passwordMatches(password, salt, storedHash) {
    const a = Buffer.from(hashPassword(password, salt), 'hex');
    const b = Buffer.from(storedHash, 'hex');
    return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Login tokens live in memory, so players must log in again after the server restarts
const sessions = new Map(); // token -> user id

function createSession(userId) {
    const token = crypto.randomBytes(32).toString('hex');
    sessions.set(token, userId);
    return token;
}

function requireLogin(req, res, next) {
    const header = req.headers.authorization || "";
    const token = header.startsWith("Bearer ") ? header.slice(7) : "";
    const userId = sessions.get(token);
    if (!userId) return res.status(401).json({ error: "Please log in." });
    req.userId = userId;
    req.token = token;
    next();
}

/* ---------- HTTP ROUTES ---------- */
app.use(express.json());

// Only HTML pages, the API and socket.io are public. This keeps aviator.db and server.js private.
app.use((req, res, next) => {
    const p = req.path;
    if (p.startsWith('/api/') || p.startsWith('/socket.io/') || p === '/' || p.endsWith('.html')) return next();
    res.status(404).end();
});
// The main address always opens the current game page (not an older index.html left in the folder)
app.get('/', (req, res) => res.redirect('/index_accounts.html'));
app.use(express.static(__dirname, { index: false }));

app.post('/api/register', (req, res) => {
    const username = String((req.body && req.body.username) || "").trim();
    const password = String((req.body && req.body.password) || "");
    if (username.length < 3 || username.length > 20) return res.status(400).json({ error: "Username must be 3 to 20 characters." });
    if (password.length < 4) return res.status(400).json({ error: "Password must be at least 4 characters." });
    if (q.findUserByName.get(username)) return res.status(409).json({ error: "That username is taken." });

    const salt = crypto.randomBytes(16).toString('hex');
    const info = q.insertUser.run(username, hashPassword(password, salt), salt, START_BALANCE, new Date().toISOString());
    const token = createSession(info.lastInsertRowid);
    res.json({ token, username, balance: START_BALANCE });
});

app.post('/api/login', (req, res) => {
    const username = String((req.body && req.body.username) || "").trim();
    const password = String((req.body && req.body.password) || "");
    const user = q.findUserByName.get(username);
    if (!user || !passwordMatches(password, user.salt, user.password_hash)) {
        return res.status(401).json({ error: "Wrong username or password." });
    }
    const token = createSession(user.id);
    res.json({ token, username: user.username, balance: user.balance });
});

app.post('/api/logout', requireLogin, (req, res) => {
    sessions.delete(req.token);
    res.json({ ok: true });
});

app.get('/api/me', requireLogin, (req, res) => {
    const user = q.findUserById.get(req.userId);
    if (!user) return res.status(404).json({ error: "Account not found." });
    res.json(user);
});

app.get('/api/history', requireLogin, (req, res) => {
    res.json(q.betsForUser.all(req.userId));
});

/* ---------- DEPOSITS AND WITHDRAWALS (play money only) ---------- */
const MAX_MONEY_MOVE = 10000;

app.post('/api/deposit', requireLogin, (req, res) => {
    const amount = round2(parseFloat(req.body && req.body.amount));
    if (!(amount > 0) || amount > MAX_MONEY_MOVE) {
        return res.status(400).json({ error: `Enter an amount between 1 and ${MAX_MONEY_MOVE}.` });
    }
    const user = q.findUserById.get(req.userId);
    const newBalance = round2(user.balance + amount);
    q.setBalance.run(newBalance, req.userId);
    q.insertTxn.run(req.userId, 'deposit', amount, newBalance, new Date().toISOString());
    sendBalance(req.userId);
    res.json({ balance: newBalance });
});

app.post('/api/withdraw', requireLogin, (req, res) => {
    const amount = round2(parseFloat(req.body && req.body.amount));
    if (!(amount > 0) || amount > MAX_MONEY_MOVE) {
        return res.status(400).json({ error: `Enter an amount between 1 and ${MAX_MONEY_MOVE}.` });
    }
    const user = q.findUserById.get(req.userId);
    if (amount > user.balance) return res.status(400).json({ error: "Not enough balance to withdraw that amount." });
    const newBalance = round2(user.balance - amount);
    q.setBalance.run(newBalance, req.userId);
    q.insertTxn.run(req.userId, 'withdrawal', amount, newBalance, new Date().toISOString());
    sendBalance(req.userId);
    res.json({ balance: newBalance });
});

app.get('/api/transactions', requireLogin, (req, res) => {
    res.json(q.txnsForUser.all(req.userId));
});

/* ---------- GAME STATE ---------- */
let gameState = "WAITING";
let currentMultiplier = 1.00;
let crashPoint = 1.00;
let gameLoopInterval = null;

// Bets keyed by "userId:pod".
//   flying = false: placed, waiting for the next take-off. Can be cancelled for a refund.
//   flying = true:  in the current flight. Can be cashed out.
let bets = {};

// Owner statistics (server only)
let ownerMetrics = {
    totalBets: 0,
    totalPayouts: 0,
    houseProfit: 0
};

function broadcastOwnerStats() {
    ownerMetrics.houseProfit = round2(ownerMetrics.totalBets - ownerMetrics.totalPayouts);
    io.to("owner_room").emit("owner_stats_update", ownerMetrics);
}

function sendBalance(userId) {
    const user = q.findUserById.get(userId);
    if (user) io.to("user_" + userId).emit("balance_update", { balance: user.balance });
}

// Tells a player which of their bets are queued or flying, so a page refresh keeps the buttons right
function sendMyBets(socket, userId) {
    const mine = {};
    for (const pod of ["A", "B"]) {
        const bet = bets[`${userId}:${pod}`];
        if (bet) mine[pod] = { stake: bet.stake, flying: bet.flying };
    }
    socket.emit('my_bets', mine);
}

// Returns the logged-in user for this socket, or null if the login has ended
function getSocketUser(socket) {
    const token = socket.data.token;
    if (!token) return null;
    return sessions.get(token) || null;
}

function generateCrashPoint() {
    const houseEdgeTrigger = Math.random();
    if (houseEdgeTrigger < 0.03) return 1.00; // 3% instant house crash
    const E = 100;
    const h = Math.random();
    return Math.floor((100 * E) / (100 - h * 99)) / 100;
}

// When a flight crashes, flying bets that were not cashed out are lost.
// Bets still queued for the next flight are left alone.
const settleCrashedBets = db.transaction(() => {
    const now = new Date().toISOString();
    for (const key of Object.keys(bets)) {
        const bet = bets[key];
        if (!bet.flying) continue;
        q.insertBet.run(bet.userId, bet.pod, bet.stake, 0, crashPoint, 0, now);
        delete bets[key];
    }
});

function startNextRound() {
    gameState = "WAITING";
    currentMultiplier = 1.00;
    crashPoint = generateCrashPoint();

    console.log(`\n--- NEW ROUND ---`);
    console.log(`Secret Crash Threshold: ${crashPoint}x`);

    io.emit('game_state', { state: "WAITING", timeRemaining: PREPARATION_TIME });

    setTimeout(() => { launchPlane(); }, PREPARATION_TIME);
}

function launchPlane() {
    gameState = "IN_PROGRESS";

    // Every bet placed before take-off now flies
    for (const key of Object.keys(bets)) bets[key].flying = true;

    io.emit('game_state', { state: "IN_PROGRESS" });

    gameLoopInterval = setInterval(() => {
        currentMultiplier += 0.01 * Math.pow(currentMultiplier, 0.4);
        currentMultiplier = round2(currentMultiplier);

        if (currentMultiplier >= crashPoint) {
            triggerCrash();
        } else {
            io.emit('multiplier_update', { multiplier: currentMultiplier });
        }
    }, TICK_RATE);
}

function triggerCrash() {
    clearInterval(gameLoopInterval);
    gameState = "CRASHED";
    console.log(`Plane crashed at ${crashPoint}x!`);

    settleCrashedBets();

    io.emit('game_state', { state: "CRASHED", finalMultiplier: crashPoint });

    setTimeout(() => { startNextRound(); }, 3000);
}

/* ---------- SOCKET EVENTS ---------- */
io.on('connection', (socket) => {
    console.log(`Connected: ${socket.id}`);

    // Tell a new visitor what is happening now (crash state is sent only in the crash event)
    if (gameState === "WAITING" || gameState === "IN_PROGRESS") {
        socket.emit('game_state', { state: gameState });
    }
    if (gameState === "IN_PROGRESS") {
        socket.emit('multiplier_update', { multiplier: currentMultiplier });
    }

    // Owner dashboard login
    socket.on("auth_as_owner", (secretKey) => {
        if (secretKey === OWNER_KEY) {
            socket.join("owner_room");
            socket.emit("owner_stats_update", ownerMetrics);
        }
    });

    // Player login for the game (guests can watch without this)
    socket.on('auth', (token) => {
        const userId = sessions.get(token);
        if (!userId || !q.findUserById.get(userId)) {
            socket.emit('auth_failed');
            return;
        }
        socket.data.token = token;
        socket.join("user_" + userId);
        sendBalance(userId);
        sendMyBets(socket, userId);
    });

    // Bets can be placed at any time. During a flight they join the next take-off.
    socket.on('place_bet', (data) => {
        const pod = data && data.pod === "B" ? "B" : "A";
        const reject = (reason) => socket.emit('bet_rejected', { pod, reason });

        const userId = getSocketUser(socket);
        if (!userId) return reject("Log in to play.");

        const amount = round2(parseFloat(data && data.amount));
        if (!(amount > 0)) return reject("Enter a valid amount.");

        const key = `${userId}:${pod}`;
        if (bets[key]) return reject("This pod already has a bet.");

        const user = q.findUserById.get(userId);
        if (amount > user.balance) return reject("Insufficient balance.");

        q.setBalance.run(round2(user.balance - amount), userId);
        bets[key] = { userId, pod, stake: amount, flying: false };

        ownerMetrics.totalBets = round2(ownerMetrics.totalBets + amount);
        broadcastOwnerStats();

        socket.emit('bet_confirmed', { pod, amount });
        sendBalance(userId);
        console.log(`Bet placed: ${user.username} pod ${pod} $${amount}`);
    });

    // Only bets that have not taken off can be cancelled. The stake is refunded.
    socket.on('cancel_bet', (data) => {
        const pod = data && data.pod === "B" ? "B" : "A";
        const userId = getSocketUser(socket);
        if (!userId) return socket.emit('cancel_rejected', { pod, reason: "Log in to play.", flying: false });

        const key = `${userId}:${pod}`;
        const bet = bets[key];
        if (!bet) return socket.emit('cancel_rejected', { pod, reason: "There is no bet to cancel.", flying: false });
        if (bet.flying) return socket.emit('cancel_rejected', { pod, reason: "This bet is already flying. Cash out instead.", flying: true });

        const user = q.findUserById.get(userId);
        delete bets[key];
        q.setBalance.run(round2(user.balance + bet.stake), userId);

        ownerMetrics.totalBets = round2(ownerMetrics.totalBets - bet.stake);
        broadcastOwnerStats();

        socket.emit('bet_cancelled', { pod });
        sendBalance(userId);
        console.log(`Bet cancelled: ${user.username} pod ${pod} $${bet.stake}`);
    });

    socket.on('cash_out', (data) => {
        const pod = data && data.pod === "B" ? "B" : "A";
        const reject = (reason) => socket.emit('cash_out_rejected', { pod, reason });

        const userId = getSocketUser(socket);
        if (!userId) return reject("Log in to play.");
        if (gameState !== "IN_PROGRESS") return reject("The plane has already crashed.");

        const key = `${userId}:${pod}`;
        const bet = bets[key];
        if (!bet || !bet.flying) return reject("There is no active bet to cash out.");

        // Pay the multiplier the player saw when they clicked (never more than the server's current one)
        const seen = parseFloat(data && data.multiplier);
        const mult = seen >= 1 && seen <= currentMultiplier ? round2(seen) : currentMultiplier;
        const payout = round2(bet.stake * mult);
        delete bets[key];

        const user = q.findUserById.get(userId);
        q.setBalance.run(round2(user.balance + payout), userId);
        q.insertBet.run(userId, pod, bet.stake, 1, mult, payout, new Date().toISOString());

        ownerMetrics.totalPayouts = round2(ownerMetrics.totalPayouts + payout);
        broadcastOwnerStats();

        socket.emit('cash_out_success', { pod, multiplier: mult, winnings: payout });
        sendBalance(userId);
        console.log(`Cash out: ${user.username} pod ${pod} at ${mult}x, won $${payout}`);
    });
});

server.listen(PORT, () => {
    console.log(`Server running on http://127.0.0.1:${PORT}`);
    startNextRound();
});
