// Dashboard JavaScript

const API_BASE = '/api';
const REFRESH_INTERVAL = 2000; // 2 seconds

let charts = {};

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    loadDashboard();

    // Refresh data periodically
    setInterval(loadDashboard, REFRESH_INTERVAL);
    setInterval(updateTime, 1000);
    
    // Update live P&L more frequently (every 2 seconds)
    setInterval(updateLivePnL, 2000);
    
    // Update balance every 5 seconds
    updateBalance();
    setInterval(updateBalance, 5000);
    
    // Update holdings every 5 seconds
    updateHoldings();
    setInterval(updateHoldings, 5000);

    // Initial time update
    updateTime();
});

// Tab Navigation
function setupTabNavigation() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            // Remove active from all tabs
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            // Add active to clicked tab
            e.target.classList.add('active');
            const tabName = e.target.dataset.tab;
            document.getElementById(tabName).classList.add('active');

            // Load tab-specific data
            if (tabName === 'trades') loadTrades();
            if (tabName === 'analytics') initCharts();
            if (tabName === 'ml-predictions') loadMLPredictions();
        });
    });
}

// Update current time
function updateTime() {
    const now = new Date();
    document.getElementById('current-time').textContent = now.toLocaleTimeString();
}

// Update Account Balance
async function updateBalance() {
    try {
        const response = await fetch(`${API_BASE}/balance`);
        const data = await response.json();
        
        const balanceElement = document.getElementById('account-balance');
        if (balanceElement && data.total_usd !== undefined) {
            balanceElement.textContent = `$${data.total_usd.toFixed(2)}`;
            
            // Add color based on balance change (if available)
            if (data.total_usd > 0) {
                balanceElement.style.color = '#10b981'; // Green
            } else {
                balanceElement.style.color = '#e2e8f0'; // Default
            }
        }
    } catch (error) {
        console.error('Error loading balance:', error);
        const balanceElement = document.getElementById('account-balance');
        if (balanceElement) {
            balanceElement.textContent = '$--.--';
        }
    }
}

// Update Holdings
async function updateHoldings() {
    try {
        const response = await fetch(`${API_BASE}/holdings`);
        const data = await response.json();
        
        const container = document.getElementById('holdings-container');
        if (!container) return;
        
        if (!data.holdings || data.holdings.length === 0) {
            container.innerHTML = '<p class="empty-message">No holdings</p>';
            return;
        }
        
        let html = '';
        data.holdings.forEach(holding => {
            html += `
                <div class="holding-item">
                    <div class="holding-header">
                        <span class="holding-currency">${holding.currency}</span>
                        <span class="holding-total">${holding.total.toFixed(4)}</span>
                    </div>
                    <div class="holding-details">
                        <span class="holding-label">Free:</span>
                        <span class="holding-value">${holding.free.toFixed(4)}</span>
                    </div>
                    <div class="holding-details">
                        <span class="holding-label">Locked:</span>
                        <span class="holding-value">${holding.locked.toFixed(4)}</span>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html;
    } catch (error) {
        console.error('Error loading holdings:', error);
        const container = document.getElementById('holdings-container');
        if (container) {
            container.innerHTML = '<p class="empty-message">Error loading holdings</p>';
        }
    }
}

// Update Signal Stats
function updateSignalStats(metrics) {
    let total_ce_signals = 0;
    let total_ml_approved = 0;
    let total_trades = 0;
    
    for (const [symbol, metric] of Object.entries(metrics.metrics || {})) {
        const stats = metric.signal_stats;
        if (stats) {
            total_ce_signals += stats.ce_signals || 0;
            total_ml_approved += stats.ml_approved || 0;
        }
        if (metric.open_trade) {
            total_trades += 1;
        }
    }
    
    const approval_rate = total_ce_signals > 0 ? (total_ml_approved / total_ce_signals * 100) : 0;
    
    const ceSignalsEl = document.getElementById('ce-signals');
    const mlApprovedEl = document.getElementById('ml-approved');
    const approvalRateEl = document.getElementById('approval-rate');
    const tradesExecutedEl = document.getElementById('trades-executed');
    
    if (ceSignalsEl) ceSignalsEl.textContent = total_ce_signals;
    if (mlApprovedEl) mlApprovedEl.textContent = total_ml_approved;
    if (approvalRateEl) approvalRateEl.textContent = `${approvalRate.toFixed(1)}%`;
    if (tradesExecutedEl) tradesExecutedEl.textContent = total_trades;
}

// Main dashboard load
async function loadDashboard() {
    try {
        const [metrics, trades] = await Promise.all([
            fetch(`${API_BASE}/metrics`).then(r => r.json()),
            fetch(`${API_BASE}/trades`).then(r => r.json())
        ]);

        updateOverviewTab(metrics, trades);
        updateCoinsTab(metrics);
        updateStatusIndicator(metrics);
        updateSignalStats(metrics);  // Add signal stats update

    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

// Update status indicator
function updateStatusIndicator(metrics) {
    const indicator = document.getElementById('status-indicator');
    const lastUpdate = document.getElementById('last-update');
    
    if (metrics.metrics && Object.keys(metrics.metrics).length > 0) {
        indicator.classList.add('active');
        indicator.classList.remove('inactive');
        indicator.textContent = '●';
    } else {
        indicator.classList.remove('active');
        indicator.classList.add('inactive');
        indicator.textContent = '●';
    }
    
    const updateTime = new Date(metrics.timestamp).toLocaleTimeString();
    lastUpdate.textContent = `Last update: ${updateTime}`;
}

// Update Overview Tab
function updateOverviewTab(metrics, trades) {
    updateSummaryStats(metrics, trades);
    updateCoinsStatus(metrics);
    updateRecentTrades(trades);
    updateOpenTrades(metrics);
}

// Update Summary Stats
function updateSummaryStats(metrics, trades) {
    const INITIAL_BALANCE = 1000000; // $1,000,000 initial balance
    
    // Calculate total P&L from closed trades
    let totalPnlValue = 0;
    const allTrades = trades.recent_trades || [];
    
    allTrades.forEach(trade => {
        if (trade.exit_price && trade.entry_price && trade.pnl_pct) {
            // Calculate P&L value for this trade
            const tradeValue = trade.entry_price * (trade.pnl_pct / 100);
            totalPnlValue += tradeValue;
        }
    });
    
    // Add unrealized P&L from open positions
    let unrealizedPnl = 0;
    for (const [symbol, metric] of Object.entries(metrics.metrics || {})) {
        if (metric.open_trade && metric.open_trade_pnl_pct) {
            unrealizedPnl += metric.open_trade_pnl_pct;
        }
    }
    
    // Calculate current balance
    const currentBalance = INITIAL_BALANCE + totalPnlValue;
    const pnlPercent = (totalPnlValue / INITIAL_BALANCE) * 100;
    
    // Update display
    const totalPnlEl = document.getElementById('total-pnl');
    const currentBalanceEl = document.getElementById('current-balance');
    const pnlPercentEl = document.getElementById('pnl-percent');
    
    if (totalPnlEl) {
        totalPnlEl.textContent = `${totalPnlValue >= 0 ? '+' : ''}$${totalPnlValue.toFixed(2)}`;
        totalPnlEl.className = `stat-value ${totalPnlValue >= 0 ? 'positive' : 'negative'}`;
    }
    
    if (currentBalanceEl) {
        currentBalanceEl.textContent = `$${currentBalance.toFixed(2)}`;
        currentBalanceEl.className = `stat-value ${currentBalance >= INITIAL_BALANCE ? 'positive' : 'negative'}`;
    }
    
    if (pnlPercentEl) {
        pnlPercentEl.textContent = `${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`;
        pnlPercentEl.className = `stat-value ${pnlPercent >= 0 ? 'positive' : 'negative'}`;
    }
}

// Update Coins Status
function updateCoinsStatus(metrics) {
    const container = document.getElementById('coins-status');
    container.innerHTML = '';

    for (const [symbol, metric] of Object.entries(metrics.metrics || {})) {
        const stats = metrics.stats[symbol] || {};
        const mlPred = metrics.ml_predictions && metrics.ml_predictions[symbol] ? metrics.ml_predictions[symbol] : null;
        const isOpen = metric.open_trade;
        const pnl = metric.open_trade_pnl_pct || 0;

        const card = document.createElement('div');
        card.className = 'coin-card';
        
        const mlInfoHtml = mlPred ? `
            <div class="coin-ml-info">
                <div class="ml-class">
                    🤖 Class: <strong>${mlPred.predicted_class !== null && mlPred.predicted_class !== undefined ? mlPred.predicted_class : 'N/A'}</strong>
                </div>
                <div class="ml-confidence">
                    Conf: <strong>${mlPred.confidence ? (mlPred.confidence * 100).toFixed(1) + '%' : 'N/A'}</strong>
                </div>
                <div class="ml-breakout">
                    Breakout: <strong>${mlPred.breakout_prob ? (mlPred.breakout_prob * 100).toFixed(1) + '%' : 'N/A'}</strong>
                </div>
            </div>
        ` : '<div class="coin-ml-info"><div class="ml-class">🤖 Class: <strong>N/A</strong></div></div>';
        
        card.innerHTML = `
            <div class="coin-symbol">
                <span class="coin-status ${isOpen ? 'active' : 'inactive'}"></span>
                ${symbol}
            </div>
            <div class="coin-price">$${(metric.current_price || 0).toFixed(2)}</div>
            <div class="coin-pnl">
                P&L: <span class="${pnl >= 0 ? 'positive' : 'negative'}">
                    ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%
                </span>
            </div>
            ${mlInfoHtml}
            <div style="font-size: 10px; margin-top: 5px;">
                Trades: ${stats.total_trades || 0}
            </div>
        `;
        container.appendChild(card);
    }
}

// Update Open Trades
function updateOpenTrades(metrics) {
    const container = document.getElementById('open-trades');
    let html = '';

    let hasOpenTrades = false;
    for (const [symbol, metric] of Object.entries(metrics.metrics || {})) {
        // Check ACTUAL position from Roostoo, not just has_order flag
        const actualPosSize = metric.actual_position_size || 0;
        const hasOpenTrade = actualPosSize > 0.001;
        
        if (hasOpenTrade) {
            hasOpenTrades = true;
            const pnl = metric.open_trade_pnl_pct || 0;
            const entryPrice = metric.actual_entry_price || metric.entry_price || 0;
            
            html += `
                <div class="trade-item">
                    <span class="trade-symbol">${symbol}</span>
                    <span>$${(metric.current_price || 0).toFixed(2)}</span>
                    <span class="trade-pnl ${pnl >= 0 ? 'positive' : 'negative'}">
                        ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%
                    </span>
                </div>
            `;
        }
    }

    container.innerHTML = html || '<p class="empty-message">No open trades</p>';
}

// Update Live P&L from dedicated endpoint
async function updateLivePnL() {
    try {
        const response = await fetch(`${API_BASE}/live-pnl`);
        const data = await response.json();
        
        const container = document.getElementById('open-trades');
        if (!container) return;
        
        let html = '';
        
        if (!data.open_trades || data.open_trades.length === 0) {
            html = '<p class="empty-message">No open trades</p>';
        } else {
            data.open_trades.forEach(trade => {
                const pnl = trade.live_pnl_pct || 0;
                const entryPrice = trade.entry_price || 0;
                const currentPrice = trade.current_price || 0;
                
                html += `
                    <div class="trade-item">
                        <div class="trade-header">
                            <span class="trade-symbol">${trade.symbol}</span>
                            <span class="trade-side ${trade.side || 'LONG'}">${trade.side || 'LONG'}</span>
                        </div>
                        <div class="trade-details">
                            <div>
                                <span class="label">Entry:</span>
                                <span class="value">$${entryPrice.toFixed(2)}</span>
                            </div>
                            <div>
                                <span class="label">Current:</span>
                                <span class="value">$${currentPrice.toFixed(2)}</span>
                            </div>
                            <div class="trade-pnl ${pnl >= 0 ? 'positive' : 'negative'}">
                                P&L: ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%
                            </div>
                        </div>
                    </div>
                `;
            });
        }
        
        container.innerHTML = html;
    } catch (error) {
        console.error('Error loading live P&L:', error);
    }
}

// Update Recent Trades
function updateRecentTrades(trades) {
    const container = document.getElementById('recent-trades');
    let html = '';
    
    const recentTrades = (trades.trades || []).slice(0, 5);
    
    if (recentTrades.length === 0) {
        container.innerHTML = '<p class="empty-message">No recent trades</p>';
        return;
    }
    
    recentTrades.forEach(trade => {
        const pnl = trade.pnl_pct || 0;
        const side = trade.side || 'N/A';
        html += `
            <div class="trade-item">
                <span class="trade-symbol">${trade.symbol}</span>
                <span class="trade-side ${side}">${side}</span>
                <span class="trade-pnl ${pnl >= 0 ? 'positive' : 'negative'}">
                    ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%
                </span>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

// Update Coins Tab
function updateCoinsTab(metrics) {
    const container = document.getElementById('coins-container');
    container.innerHTML = '';
    
    for (const [symbol, metric] of Object.entries(metrics.metrics || {})) {
        const stats = metrics.stats[symbol] || {};
        const isOpen = metric.open_trade;
        const probs = metric.last_predicted_probs || [0, 0, 0, 0];
        
        const card = document.createElement('div');
        card.className = 'coin-detail-card';
        card.innerHTML = `
            <div class="coin-detail-header">
                <div class="coin-name">${symbol}</div>
                <span class="coin-status-badge ${isOpen ? 'active' : 'inactive'}">
                    ${isOpen ? 'TRADING' : 'IDLE'}
                </span>
            </div>
            
            <div class="coin-detail-stat">
                <label>Current Price</label>
                <value>$${(metric.current_price || 0).toFixed(2)}</value>
            </div>
            
            <div class="coin-detail-stat">
                <label>Open Trade P&L</label>
                <value class="${metric.open_trade_pnl_pct >= 0 ? 'positive' : 'negative'}">
                    ${metric.open_trade_pnl_pct >= 0 ? '+' : ''}${(metric.open_trade_pnl_pct || 0).toFixed(2)}%
                </value>
            </div>
            
            <div class="coin-detail-stat">
                <label>Total Trades</label>
                <value>${stats.total_trades || 0}</value>
            </div>
            
            <div class="coin-detail-stat">
                <label>Win Rate</label>
                <value>${stats.win_rate ? stats.win_rate.toFixed(1) : 0}%</value>
            </div>
            
            <div class="coin-detail-stat">
                <label>Total P&L</label>
                <value class="${stats.total_pnl >= 0 ? 'positive' : 'negative'}">
                    ${stats.total_pnl >= 0 ? '+' : ''}${(stats.total_pnl || 0).toFixed(2)}%
                </value>
            </div>
            
            <div class="ml-probabilities">
                <div style="font-weight: bold; margin-bottom: 10px;">ML Class Probabilities</div>
                <div class="ml-prob-bar">
                    <span class="ml-prob-label">Class 0</span>
                    <div class="ml-prob-bar-container">
                        <div class="ml-prob-bar-fill" style="width: ${(probs[0] || 0) * 100}%"></div>
                    </div>
                    <span class="ml-prob-value">${((probs[0] || 0) * 100).toFixed(1)}%</span>
                </div>
                <div class="ml-prob-bar">
                    <span class="ml-prob-label">Class 1</span>
                    <div class="ml-prob-bar-container">
                        <div class="ml-prob-bar-fill" style="width: ${(probs[1] || 0) * 100}%"></div>
                    </div>
                    <span class="ml-prob-value">${((probs[1] || 0) * 100).toFixed(1)}%</span>
                </div>
                <div class="ml-prob-bar">
                    <span class="ml-prob-label">Class 2</span>
                    <div class="ml-prob-bar-container">
                        <div class="ml-prob-bar-fill" style="width: ${(probs[2] || 0) * 100}%"></div>
                    </div>
                    <span class="ml-prob-value">${((probs[2] || 0) * 100).toFixed(1)}%</span>
                </div>
                <div class="ml-prob-bar">
                    <span class="ml-prob-label">Class 3</span>
                    <div class="ml-prob-bar-container">
                        <div class="ml-prob-bar-fill" style="width: ${(probs[3] || 0) * 100}%"></div>
                    </div>
                    <span class="ml-prob-value">${((probs[3] || 0) * 100).toFixed(1)}%</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    }
}

// Load Trades
async function loadTrades() {
    try {
        const data = await fetch(`${API_BASE}/trades`).then(r => r.json());
        updateTradesTable(data.trades || []);
    } catch (error) {
        console.error('Error loading trades:', error);
    }
}

// Update Trades Table
function updateTradesTable(trades) {
    const tbody = document.getElementById('trades-tbody');
    tbody.innerHTML = '';
    
    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 20px;">No trades</td></tr>';
        return;
    }
    
    trades.forEach(trade => {
        const entryTime = new Date(trade.entry_time).toLocaleString();
        const exitTime = trade.exit_time ? new Date(trade.exit_time).toLocaleString() : 'Open';
        const pnl = trade.pnl_pct || 0;
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${trade.symbol}</strong></td>
            <td>${entryTime}</td>
            <td>$${(trade.entry_price || 0).toFixed(2)}</td>
            <td><span class="trade-side ${trade.side}">${trade.side}</span></td>
            <td>${exitTime}</td>
            <td>${trade.exit_price ? '$' + trade.exit_price.toFixed(2) : '-'}</td>
            <td class="${pnl >= 0 ? 'positive' : 'negative'}" style="font-weight: bold;">
                ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%
            </td>
            <td>${trade.predicted_class || '-'}</td>
            <td>${trade.reason || '-'}</td>
        `;
        tbody.appendChild(row);
    });
}

// Initialize Charts
async function initCharts() {
    try {
        const data = await fetch(`${API_BASE}/trades`).then(r => r.json());
        const trades = data.trades || [];
        
        if (trades.length === 0) {
            console.log('No trades to display in charts');
            return;
        }
        
        createPnLChart(trades);
        createWinRateChart(trades);
        createClassChart(trades);
    } catch (error) {
        console.error('Error initializing charts:', error);
    }
}

// Create P&L Chart
function createPnLChart(trades) {
    const ctx = document.getElementById('pnl-chart');
    if (!ctx) return;
    
    const cumPnL = [];
    let sum = 0;
    trades.reverse().forEach(trade => {
        sum += trade.pnl_pct || 0;
        cumPnL.push(sum);
    });
    
    if (charts.pnl) charts.pnl.destroy();
    
    charts.pnl = new Chart(ctx, {
        type: 'line',
        data: {
            labels: trades.map((_, i) => `Trade ${i + 1}`),
            datasets: [{
                label: 'Cumulative P&L (%)',
                data: cumPnL,
                borderColor: '#007bff',
                backgroundColor: 'rgba(0, 123, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: true }
            },
            scales: {
                y: {
                    title: { display: true, text: 'P&L (%)' }
                }
            }
        }
    });
}

// Create Win Rate Chart
function createWinRateChart(trades) {
    const ctx = document.getElementById('win-rate-chart');
    if (!ctx) return;
    
    const byCoin = {};
    trades.forEach(trade => {
        if (!byCoin[trade.symbol]) {
            byCoin[trade.symbol] = { total: 0, wins: 0 };
        }
        byCoin[trade.symbol].total += 1;
        if ((trade.pnl_pct || 0) > 0) {
            byCoin[trade.symbol].wins += 1;
        }
    });
    
    const labels = Object.keys(byCoin);
    const winRates = labels.map(coin => 
        (byCoin[coin].wins / byCoin[coin].total * 100).toFixed(1)
    );
    
    if (charts.winRate) charts.winRate.destroy();
    
    charts.winRate = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Win Rate (%)',
                data: winRates,
                backgroundColor: '#28a745'
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });
}

// Create Class Distribution Chart
function createClassChart(trades) {
    const ctx = document.getElementById('class-chart');
    if (!ctx) return;
    
    const classCounts = [0, 0, 0, 0];
    trades.forEach(trade => {
        const cls = trade.predicted_class || 0;
        if (cls >= 0 && cls < 4) {
            classCounts[cls] += 1;
        }
    });
    
    if (charts.class) charts.class.destroy();
    
    charts.class = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['No Trade (0)', '1-3% (1)', '3-5% (2)', '>5% (3)'],
            datasets: [{
                data: classCounts,
                backgroundColor: [
                    '#6c757d',
                    '#007bff',
                    '#ffc107',
                    '#28a745'
                ]
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: true, position: 'bottom' }
            }
        }
    });
}
" "  
// ========================================
// ML PREDICTIONS TAB FUNCTIONS
// ========================================

async function loadMLPredictions() {
    try {
        const response = await fetch(`${API_BASE}/ml-predictions`);
        const data = await response.json();
        
        updateMLPredictionsLive(data.predictions);
        updateMLPredictionsHistory(data.recent_history);
        updateMLHistoryCharts(data.recent_history);
        updateCoinHistoryBlocks(data.recent_history);
    } catch (error) {
        console.error('Error loading ML predictions:', error);
    }
}

function updateMLPredictionsLive(predictions) {
    const container = document.getElementById('ml-predictions-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    for (const [symbol, pred] of Object.entries(predictions)) {
        const ml = pred.ml_prediction;
        const card = document.createElement('div');
        card.className = 'ml-prediction-card';
        
        const recommendationClass = ml?.recommendation?.includes('ENTER') ? 'buy-signal' : 
                                   ml?.recommendation === 'WAIT_LOW_CONFIDENCE' ? 'wait-signal' : 'no-trade';
        
        card.innerHTML = `
            <h3>🪙 ${symbol}</h3>
            <div class="ml-status-grid">
                <div class="ml-stat">
                    <span class="label">Status:</span>
                    <span class="value ${pred.is_running ? 'running' : 'stopped'}">
                        ${pred.is_running ? '🟢 Running' : '🔴 Stopped'}
                    </span>
                </div>
                <div class="ml-stat">
                    <span class="label">Trade:</span>
                    <span class="value">${pred.has_open_trade ? '🔴 Open' : '🟢 None'}</span>
                </div>
            </div>
            ${ml ? `
            <div class="ml-prediction-details">
                <div class="ml-main-stat">
                    <span class="pred-class">Class ${ml.predicted_class || 'N/A'}</span>
                    <span class="pred-confidence">${(ml.confidence * 100 || 0).toFixed(1)}%</span>
                </div>
                <div class="ml-stat-row">
                    <span>Breakout Prob: <strong>${(ml.breakout_prob * 100 || 0).toFixed(1)}%</strong></span>
                </div>
                <div class="ml-stat-row">
                    <span>TP: <strong class="tp-value">+${(ml.tp_target || 0).toFixed(1)}%</strong></span>
                    <span>SL: <strong class="sl-value">-${(ml.sl_limit || 0).toFixed(1)}%</strong></span>
                </div>
                <div class="ml-recommendation ${recommendationClass}">
                    ${ml.recommendation || 'N/A'}
                </div>
                <div class="ml-timestamp">
                    Updated: ${ml.timestamp ? new Date(ml.timestamp).toLocaleTimeString() : 'N/A'}
                </div>
            </div>
            ` : `
            <div class="ml-no-data">
                <p>No prediction data available</p>
            </div>
            `}
        `;
        container.appendChild(card);
    }
}

function updateMLPredictionsHistory(history) {
    const tbody = document.getElementById('ml-history-tbody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    history.forEach(pred => {
        const row = tbody.insertRow();
        const recommendationClass = pred.recommendation?.includes('ENTER') ? 'text-green' : 
                                   pred.recommendation === 'WAIT_LOW_CONFIDENCE' ? 'text-yellow' : 'text-gray';
        
        row.innerHTML = `
            <td><strong>${pred.symbol}</strong></td>
            <td>${pred.timestamp ? new Date(pred.timestamp).toLocaleString() : 'N/A'}</td>
            <td>Class ${pred.predicted_class || 'N/A'}</td>
            <td>${(pred.confidence * 100 || 0).toFixed(1)}%</td>
            <td>${(pred.breakout_prob * 100 || 0).toFixed(1)}%</td>
            <td class="${recommendationClass}">${pred.recommendation || 'N/A'}</td>
            <td class="tp-value">+${(pred.tp_target || 0).toFixed(1)}%</td>
            <td class="sl-value">-${(pred.sl_limit || 0).toFixed(1)}%</td>
        `;
    });
}

// ========================================
// ML HISTORY CHARTS
// ========================================

let mlBreakoutChart = null;

function updateMLHistoryCharts(history) {
    // Group by coin
    const byCoin = {};
    history.forEach(pred => {
        if (!byCoin[pred.symbol]) {
            byCoin[pred.symbol] = [];
        }
        byCoin[pred.symbol].push(pred);
    });
    
    // Sort each coin's history by timestamp
    for (const symbol in byCoin) {
        byCoin[symbol].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    }
    
    // Breakout Probability Chart (last 12 predictions)
    const breakoutCtx = document.getElementById('ml-breakout-chart').getContext('2d');
    
    const breakoutDatasets = Object.keys(byCoin).map((symbol, index) => ({
        label: symbol,
        data: byCoin[symbol].slice(-12).map(p => (p.breakout_prob || 0) * 100),  // Last 12 candles
        borderColor: getChartColor(index),
        backgroundColor: getChartColor(index, 0.2),
        tension: 0.4,
        fill: false
    }));
    
    if (mlBreakoutChart) {
        mlBreakoutChart.destroy();
    }
    
    mlBreakoutChart = new Chart(breakoutCtx, {
        type: 'line',
        data: {
            labels: byCoin[Object.keys(byCoin)[0]]?.slice(-12).map(p => {
                const date = new Date(p.timestamp);
                return `${date.getHours()}:${date.getMinutes().toString().padStart(2, '0')}`;
            }) || [],
            datasets: breakoutDatasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: true,
                    text: 'Breakout Probability Over Time (Last 12 Candles - 3 Hours)',
                    color: '#e2e8f0',
                    font: { size: 14 }
                },
                legend: {
                    labels: { color: '#e2e8f0' }
                },
                annotation: {
                    annotations: {
                        thresholdLine: {
                            type: 'line',
                            yMin: 70,  // ML_CONFIDENCE_THRESHOLD = 0.7 (70%)
                            yMax: 70,
                            borderColor: 'rgba(255, 159, 64, 0.8)',
                            borderWidth: 2,
                            borderDash: [6, 6],
                            label: {
                                display: true,
                                content: 'Threshold (70%)',
                                position: 'end',
                                backgroundColor: 'rgba(255, 159, 64, 0.8)',
                                color: '#fff',
                                font: { size: 11, weight: 'bold' }
                            }
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    grid: { color: '#334155' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { color: '#334155' },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });
}

// ========================================
// INDIVIDUAL COIN HISTORY BLOCKS
// ========================================

function updateCoinHistoryBlocks(history) {
    const container = document.getElementById('coin-history-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    // Group by coin
    const byCoin = {};
    history.forEach(pred => {
        if (!byCoin[pred.symbol]) {
            byCoin[pred.symbol] = [];
        }
        byCoin[pred.symbol].push(pred);
    });
    
    // Create block for each coin
    for (const [symbol, predictions] of Object.entries(byCoin)) {
        const block = document.createElement('div');
        block.className = 'coin-history-block';
        
        // Sort by timestamp (newest first)
        predictions.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        
        // Get latest prediction
        const latest = predictions[0];
        const latestClass = latest?.recommendation?.includes('ENTER') ? 'buy-signal' : 
                           latest?.recommendation === 'WAIT_LOW_CONFIDENCE' ? 'wait-signal' : 'no-trade';
        
        // Get class probabilities from latest prediction
        const probs = latest?.probabilities || [0, 0, 0, 0];
        
        block.innerHTML = `
            <div class="coin-history-header">
                <h3>🪙 ${symbol}</h3>
                <div class="latest-rec ${latestClass}">
                    ${latest?.recommendation || 'N/A'}
                </div>
            </div>
            
            <div class="coin-history-stats">
                <div class="stat-item">
                    <span class="label">Class:</span>
                    <span class="value">${latest?.predicted_class ?? 'N/A'}</span>
                </div>
                <div class="stat-item">
                    <span class="label">Conf:</span>
                    <span class="value">${(latest?.confidence || 0) * 100 > 0 ? (latest.confidence * 100).toFixed(1) + '%' : 'N/A'}</span>
                </div>
                <div class="stat-item">
                    <span class="label">Breakout:</span>
                    <span class="value">${(latest?.breakout_prob || 0) * 100 > 0 ? (latest.breakout_prob * 100).toFixed(1) + '%' : 'N/A'}</span>
                </div>
            </div>
            
            <div class="coin-class-probs">
                <h4>Class Probabilities</h4>
                <div class="probs-bars">
                    <div class="prob-row">
                        <span class="prob-label">Class 0:</span>
                        <div class="prob-bar-container">
                            <div class="prob-bar" style="width: ${(probs[0] || 0) * 100}%; background: #ef4444;"></div>
                        </div>
                        <span class="prob-value">${((probs[0] || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div class="prob-row">
                        <span class="prob-label">Class 1:</span>
                        <div class="prob-bar-container">
                            <div class="prob-bar" style="width: ${(probs[1] || 0) * 100}%; background: #10b981;"></div>
                        </div>
                        <span class="prob-value">${((probs[1] || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div class="prob-row">
                        <span class="prob-label">Class 2:</span>
                        <div class="prob-bar-container">
                            <div class="prob-bar" style="width: ${(probs[2] || 0) * 100}%; background: #3b82f6;"></div>
                        </div>
                        <span class="prob-value">${((probs[2] || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div class="prob-row">
                        <span class="prob-label">Class 3:</span>
                        <div class="prob-bar-container">
                            <div class="prob-bar" style="width: ${(probs[3] || 0) * 100}%; background: #8b5cf6;"></div>
                        </div>
                        <span class="prob-value">${((probs[3] || 0) * 100).toFixed(1)}%</span>
                    </div>
                </div>
            </div>
            
            <div class="coin-history-list">
                <table class="history-mini-table">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Class</th>
                            <th>Conf</th>
                            <th>Breakout</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${predictions.slice(0, 10).map(pred => {
                            const p = pred.probabilities || [0, 0, 0, 0];
                            return `
                            <tr>
                                <td>${pred.timestamp ? new Date(pred.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'N/A'}</td>
                                <td>${pred.predicted_class ?? 'N/A'}</td>
                                <td>${(pred.confidence || 0) * 100 > 0 ? (pred.confidence * 100).toFixed(0) + '%' : '-'}</td>
                                <td>${(pred.breakout_prob || 0) * 100 > 0 ? (pred.breakout_prob * 100).toFixed(0) + '%' : '-'}</td>
                            </tr>
                        `}).join('')}
                    </tbody>
                </table>
            </div>
        `;
        
        container.appendChild(block);
    }
}

// Helper: Get chart color by index
function getChartColor(index, alpha = 1) {
    const colors = [
        `rgba(59, 130, 246, ${alpha})`,   // Blue
        `rgba(16, 185, 129, ${alpha})`,   // Green
        `rgba(245, 158, 11, ${alpha})`,   // Amber
        `rgba(139, 92, 246, ${alpha})`,   // Purple
        `rgba(239, 68, 68, ${alpha})`     // Red
    ];
    return colors[index % colors.length];
}
