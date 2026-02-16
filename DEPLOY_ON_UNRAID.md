# Deploying Daily Brief to Unraid

This guide walks you through deploying the `daily-brief` application stack (Postgres, Miniflux, and the Python Brief Generator) to your Unraid NAS using the **Docker Compose Manager** plugin.

## Prerequisites

1.  **Unraid OS**: Running version 6.9 or newer.
2.  **Community Applications Plugin**: Installed (standard on most Unraid servers).
3.  **Docker Compose Manager Plugin**:
    - Go to **Apps** tab in Unraid.
    - Search for "Docker Compose Manager".
    - Install it.

## Step 1: Prepare the Files

You need to get the project files onto your Unraid server. The standard location for Docker app data is `/mnt/user/appdata`.

1.  **Access your Unraid share**:
    - Connect to your Unraid server's `appdata` share via SMB (Windows Network) or SSH.
2.  **Create a directory**:
    - Create a folder named `daily-brief` inside `appdata`.
    - Path: `\\TOWER\appdata\daily-brief` (or `/mnt/user/appdata/daily-brief`).
3.  **Copy Files**:
    - Copy the contents of this repository into that folder using your file explorer or terminal.
    - **Crucial Files**:
        - `compose.yml`
        - `.env.example` -> Rename to `.env`
        - `daily-brief/` folder (containing `Dockerfile` and `main.py`)

## Step 2: Configuration

1.  **Edit `.env`**:
    - Open the `.env` file you just created (renamed from `.env.example`) on the server.
    - You can use the Unraid terminal (`nano /mnt/user/appdata/daily-brief/.env`) or a text editor over the network share.
2.  **Set Basic Variables**:
    - `POSTGRES_PASSWORD`: Set a strong password.
    - `ADMIN_PASSWORD`: Set a password for the Miniflux admin user.
    - `MINIFLUX_PORT`: Choose the port for the web interface (default: 8300).
    - `GEMINI_API_KEY`: Paste your generic Google Gemini API key.
    - `DISCORD_WEBHOOK_URL`: Paste your Discord Webhook URL.
    - `MINIFLUX_BASE_URL`: Set this to `http://YOUR_UNRAID_IP:PORT` (e.g., `http://192.168.1.100:8300`). Ensure the port matches `MINIFLUX_PORT`.

## Step 3: First Run (Miniflux Setup)

We need to start Miniflux first to generate an API token for the Python script.

1.  **Go to Unraid Web UI -> Docker**.
2.  Scroll down to the **Docker Compose** section (added by the plugin).
3.  You should see the `daily-brief` project (if not, click "Add New Stack", name it `daily-brief`, and paste the contents of `compose.yml`).
4.  **Click "Compose Up"** (or the Play button).
    - This will pull images and start the containers.
    - The `ai-daily-brief` container might fail or log errors because it doesn't have a valid API token yet. **This is normal.**

## Step 4: Get Miniflux API Token

1.  Open your browser and go to `http://YOUR_UNRAID_IP:8081`.
2.  Login with `admin` and the password you set in `ADMIN_PASSWORD`.
3.  Go to **Settings** -> **API Keys**.
4.  Click **Create a new API key**.
    - Description: `Daily Brief Bot`
5.  **Copy the generated API Key**.

## Step 5: Final Configuration

1.  **Update `.env`**:
    - Open `.env` again.
    - Paste the API key into `MINIFLUX_API_TOKEN`.
2.  **Restart the Stack**:
    - Go back to Unraid Docker UI.
    - Find the `daily-brief` stack.
    - Click **"Compose Down"** then **"Compose Up"** (or "Update Stack" if available) to pick up the new environment variable.

## Step 6: Verify

1.  Check the logs of the `daily-brief-ai-daily-brief-1` container.
    - Click the icon -> **Logs**.
2.  You should see it start up and schedule the job (e.g., `Job scheduled for 08:00...`).
3.  **Test Run (Optional)**:
    - You can force a run by executing a command inside the container, or just wait for the scheduled time.

## Troubleshooting

-   **"Connection refused"**: Ensure Miniflux is fully running (`daily-brief-miniflux-1`) before the AI script tries to connect. The `depends_on` in `compose.yml` handles this, but startup can be slow.
-   **Permission Errors**: If using SMB to copy files, ensure the `daily-brief` folder permissions allow the Docker user to read them. Running `chmod -R 755 /mnt/user/appdata/daily-brief` in the Unraid terminal can fix this.
-   **Postgres Unhealthy**: Run `docker compose logs postgres` to see why it's failing. If it's a timeout (common on first run with HDDs), the updated `compose.yml` includes a `start_period` to help. You can also try starting just postgres first: `docker compose up -d postgres`.

## Manual Trigger / Testing

To force a "Daily Brief" run immediately without waiting for the scheduled time:

1.  **Open Unraid Terminal**.
2.  Run the following command:
    ```bash
    docker exec -it daily-brief-ai-daily-brief-1 python /app/main.py --now
    ```
    *(Note: Adjust the container name `daily-brief-ai-daily-brief-1` if yours is different. You can find it with `docker ps`)*.

3.  Check your Discord for the message!
