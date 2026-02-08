/**
 * PM2 Ecosystem Configuration
 *
 * This file configures PM2 to manage main_watcher.py as the top-level
 * supervisor process. main_watcher.py then manages its own children
 * (gmail_watcher.py, orchestrator.py) internally.
 *
 * Setup:
 *   npm install -g pm2
 *   pm2 start ecosystem.config.js
 *   pm2 save
 *   pm2 startup          # generates OS-specific auto-start command
 *
 * Commands:
 *   pm2 status            # check process status
 *   pm2 logs ai-employee  # tail logs
 *   pm2 restart ai-employee
 *   pm2 stop ai-employee
 *   pm2 delete ai-employee
 */

module.exports = {
  apps: [
    {
      name: "ai-employee",
      script: "main_watcher.py",
      interpreter: __dirname + "/venv/Scripts/python.exe",
      cwd: __dirname,

      // Restart policy
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      restart_delay: 5000,

      // Logging
      log_file: "./logs/pm2_ai_employee.log",
      error_file: "./logs/pm2_ai_employee_error.log",
      out_file: "./logs/pm2_ai_employee_out.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",

      // Environment
      env: {
        PYTHONUNBUFFERED: "1",
      },

      // Graceful shutdown
      kill_timeout: 15000,
      shutdown_with_message: true,

      // Watch is OFF — main_watcher handles its own children
      watch: false,
    },
  ],
};
