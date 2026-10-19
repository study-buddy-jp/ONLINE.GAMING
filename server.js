// A simple local collection to hold live player profiles
// Format: phone_number => { username: string, balance: number }
const userWallets = new Map();
const activePlayers = new Map();

// Let's seed your specific developer identity into the system for local testing
userWallets.set("254712345678", {
    username: "User_Dev",
    balance: 100.00 // Starts with 100 KES to test game deductions
});

const express = require('express');
const http = require('http');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: "*" } });

app.use(express.static(__dirname));

// 1. App Configuration & Middleware
app.use(express.json()); // Moved up here so it handles all parsing cleanly

// Define your static files specifically for a public folder if you have one, 
// or remove the static line if you are serving individual endpoints.
// app.use(express.static(path.join(__dirname, 'public'))); 

const PORT = process.env.PORT || 3000;
const OWNER_KEY = process.env.OWNER_KEY || "change-me-owner-key";
const TICK_RATE = 100;
const PREPARATION_TIME = 5000;

const path = require('path');

// Add express.json() middleware at the top if you don't have it, so your server reads JSON payloads
app.use(express.json());


// Route to serve the primary game layout page
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

// Route to serve your accounts registration/login splash system
app.get('/login', (req, res) => {
    res.sendFile(path.join(__dirname, 'index_accounts.html'));
});

// Verification handler to authorize users logging into your crash app platform
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;

// Attach the interactive event listener when the DOM content locks in
document.getElementById('initiate-deposit-btn').addEventListener('click', async () => {
    const amountInput = document.getElementById('deposit-amount').value;
    const phoneInput = document.getElementById('deposit-phone').value;
    const feedbackText = document.getElementById('deposit-status-feedback');

    // 1. Core Front-End Validation Check
    if (!amountInput || !phoneInput) {
        feedbackText.textContent = "⚠️ Please fill out both the amount and phone number fields.";
        feedbackText.style.color = "#ef4444";
        return;
    }

    if (!phoneInput.startsWith("254") || phoneInput.length !== 12) {
        feedbackText.textContent = "⚠️ Invalid format. Phone number must start with 254 (e.g., 254712345678).";
        feedbackText.style.color = "#ef4444";
        return;
    }

    // 2. Transition button UI state to prevent multiple accidental click actions
    const depositButton = document.getElementById('initiate-deposit-btn');
    depositButton.disabled = true;
    depositButton.textContent = "Processing... Please wait";
    feedbackText.textContent = "🚀 Dispatching transaction bundle to network server...";
    feedbackText.style.color = "#60a5fa";

    try {
        // Fetch current active local user token context if your system tracks it
        const localUserIdentity = localStorage.getItem('username') || "User_Dev";

        // 3. Fire the asynchronous checkout payload up to your Express endpoint
        // NOTE: If using an alternative port or domain, ensure the URL path matches perfectly
        const response = await fetch('/api/initiate-deposit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                userId: localUserIdentity,
                amount: parseFloat(amountInput),
                phone: phoneInput
            })
        });

        const data = await response.json();

        // 4. Handle Server Response Actions
        if (response.ok && data.status === "success") {
            feedbackText.textContent = "📲 STK Push Sent! Please check your smartphone and enter your M-Pesa PIN to authorize.";
            feedbackText.style.color = "#22c55e";
        } else {
            feedbackText.textContent = `❌ Deposit Initiation Failed: ${data.error || "Unknown Error"}`;
            feedbackText.style.color = "#ef4444";
            // Re-enable button so they can try again
            depositButton.disabled = false;
            depositButton.textContent = "Send STK Push Request";
        }

    } catch (error) {
        console.error("Monetization transmission framework exception:", error);
        feedbackText.textContent = "❌ Connection timed out. Is your backend game server currently running?";
        feedbackText.style.color = "#ef4444";
        depositButton.disabled = false;
        depositButton.textContent = "Send STK Push Request";
    }
});

    // Verification route to handle the automated startup auth check from your image
app.get('/api/me', (req, res) => {
    // 1. Grab the token from the request header metadata block
    const authHeader = req.headers.authorization;
    
    console.log(`📡 Auto-authenticating current page session via token header: ${authHeader}`);

    // 2. For local testing, bypass token decoding and automatically provide the exact
    // JSON keys your frontend script is looking for (u.username and u.balance)
    return res.status(200).json({
        username: "User_Dev",
        balance: 100.00 // Matches your local state dictionary seed value
    });
});
    
    console.log(`🔑 Login authentication requested for user: ${username}`);
    
    // For local development testing, accept any incoming request automatically
    if (username && password) {
        return res.status(200).json({ 
            success: true, 
            message: "Authentication successful",
            user: { username: username, balance: 100.00 } // Link to seed wallet data
        });
    }
    
    res.status(400).json({ success: false, error: "Invalid username or password fields" });
});

// The public endpoint tor pings upon transaction completion
app.post('/api/payment-Webhook', (req, res) => {
    const { status, amount, phone } = req.body;

    console.log(`\n--- 📥 INCOMING WEBHOOK TRANSACTION ---`);
    console.log(`Phone: ${phone} | Amount: ${amount} KES | Status: ${status}`);

    if (status === 'successful') {
        // 1. Locate the profile within your wallet ledger map
        if (userWallets.has(phone)) {
            const playerProfile = userWallets.get(phone);
            
            // 2. Perform the financial credit addition safely
            playerProfile.balance += parseFloat(amount);
            
            console.log(`💰 Success! Credited KES ${amount} to ${playerProfile.username}. New Balance: KES ${playerProfile.balance}`);

            // 3. Inform the client layout over Socket.io right away to refresh the UI indicator
            // We use io.emit for our local test, but in production, you would target the specific socket ID
            io.emit('wallet_balance_updated', {
                phone: phone,
                newBalance: playerProfile.balance
            });

            // 4. Respond with an HTTP 200 code so the aggregator knows your server processed it cleanly
            return res.status(200).json({ message: "Wallet successfully credited" });
        } else {
            console.log(`⚠️ Transaction rejected: No registered wallet exists for phone ${phone}`);
            return res.status(404).json({ error: "User account profile not found" });
        }
    }

    res.status(400).json({ error: "Transaction was not successful" });
});


// Game State Variables
let gameState = "WAITING";
let currentMultiplier = 1.00;
let crashPoint = 1.00;
let gameLoopInterval = null;

// Bets for the current round, keyed by "socketId:pod" (pod = "A" or "B")
let activeBets = {};

// Owner statistics (kept on the server only)
let ownerMetrics = {
    totalBets: 0,
    totalPayouts: 0,
    houseProfit: 0
};

function round2(n) {
    return Math.round(n * 100) / 100;
}

function broadcastOwnerStats() {
    ownerMetrics.houseProfit = round2(ownerMetrics.totalBets - ownerMetrics.totalPayouts);
    io.to("owner_room").emit("owner_stats_update", ownerMetrics);
}

function generateCrashPoint() {
    const houseEdgeTrigger = Math.random();
    if (houseEdgeTrigger < 0.03) return 1.00; // 3% instant house crash
    const E = 100;
    const h = Math.random();
    return Math.floor((100 * E) / (100 - h * 99)) / 100;
}

function startNextRound() {
    gameState = "WAITING";
    currentMultiplier = 1.00;
    crashPoint = generateCrashPoint();
    activeBets = {}; // Reset bets for the new round

    console.log(`\n--- NEW ROUND ---`);
    console.log(`Secret Crash Threshold: ${crashPoint}x`);

    io.emit('game_state', { state: "WAITING", timeRemaining: PREPARATION_TIME });

    setTimeout(() => { launchPlane(); }, PREPARATION_TIME);
}

function launchPlane() {
    gameState = "IN_PROGRESS";
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

    // Players who did not cash out have already been counted in totalBets and lose their stake
    io.emit('game_state', { state: "CRASHED", finalMultiplier: crashPoint });

    setTimeout(() => { startNextRound(); }, 3000);
}

io.on('connection', (socket) => {
    console.log(`Player Connected: ${socket.id}`);

    // Owner dashboard login block
    socket.on("auth_as_owner", (secretKey) => {
        if (secretKey === OWNER_KEY) {
            socket.join("owner_room");
            socket.emit("owner_stats_update", ownerMetrics);
        }
    });
    
        socket.emit('bet_rejected', { reason: "Insufficient wallet balance to place this stake." })
        // Action A: Player places a bet during the waiting window
       socket.on('placeBet', (data) => {
    const playerPhone = "254712345678"; // Local test anchor phone number
    const playerWallet = userWallets.get(playerPhone);
    const betSize = parseFloat(data.amount);

    // 1. Balance Gatekeeper Check
    if (playerWallet && playerWallet.balance >= betSize) {
        
        // 2. Deduct money from the wallet balance ledger immediately
        playerWallet.balance -= betSize;
        
        // 3. Fire real-time socket push to update the frontend UI indicator
        socket.emit('wallet_balance_updated', { 
            phone: playerPhone, 
            newBalance: playerWallet.balance 
        });

        console.log(`✅ Bet locked in: ${betSize} KES deducted from account.`);

        // 4. RESTORE BASE TRACKING LOGIC (Using your exact variable name!)
        // This registers the user details into your existing activeBets collection
        activeBets.set(socket.id, {
            username: data.username || "You",
            betAmount: betSize,
            targetRate: parseFloat(data.targetRate) || 2.00,
            autoCashOutEnabled: data.autoCashOutEnabled || false,
            cashedOut: false
        });

        // Inform the client file that the transaction went through smoothly
        socket.emit('betConfirmed');
           
    } else {
        // 5. Reject the bet placement completely if funds are insufficient
        socket.emit('bet_rejected', { 
            reason: "Insufficient wallet balance to place this stake." 
        });
    }
});

     

    // Action B: Player hits Cash Out during flight
    socket.on('cash_out', (data) => {
        if (gameState !== "IN_PROGRESS") return;

        const key = `${socket.id}:${(data && data.pod) || "A"}`;
        const playerBet = activeBets[key];
        if (!playerBet || playerBet.cashedOut) return;

        const winnings = round2(playerBet.betAmount * currentMultiplier);
        playerBet.cashedOut = true;

        ownerMetrics.totalPayouts = round2(ownerMetrics.totalPayouts + winnings);
        broadcastOwnerStats();

        socket.emit('cash_out_success', {
            multiplier: currentMultiplier,
            winnings: winnings
        });
        console.log(`Player ${socket.id} Cashed Out at ${currentMultiplier}x! Won: $${winnings}`);
    });

    socket.on('disconnect', () => {
        for (const key of Object.keys(activeBets)) {
            if (key.startsWith(socket.id + ":")) delete activeBets[key];
        }
    });
});

server.listen(PORT, () => {
    console.log(`Server running on http://127.0.0.1:${PORT}`);
    startNextRound();
});
