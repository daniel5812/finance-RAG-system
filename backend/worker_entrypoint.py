"""
worker_entrypoint.py — Independent Indexing Worker Process.

This script runs in a standalone container and:
1.  Connects to PostgreSQL, Redis, and Pinecone.
2.  Loads ML models into memory.
3.  Listens for tasks on the Redis list "tasks:document_indexing".
4.  Processes each task using the indexing pipeline in documents/worker.py.
"""

import asyncio
import json
import signal
import sys
from datetime import datetime, time as dt_time, timedelta

import core.connections as connections
from core.connections import load_ml_models, redis_client, pinecone_index
from core.db import get_pool, close_pool
from core.logger import get_logger
from documents.worker import process_document_worker
from financial.providers.fx import BOIProvider
from financial.providers.holdings import HoldingsProvider

logger = get_logger("worker")

# ── Graceful Shutdown ────────────────────────────────────────────────────────

shutdown_event = asyncio.Event()

def handle_signal():
    logger.info("Shutdown signal received...")
    shutdown_event.set()

# ── Scheduler Loop ───────────────────────────────────────────────────────────

async def scheduler_loop():
    """
    Periodically pushes scheduled tasks (FX, Holdings) to the Redis queue.
    Runs once a day at 02:00 AM.
    """
    logger.info("Scheduler loop started.")
    
    while not shutdown_event.is_set():
        try:
            now = datetime.now()
            # Calculate time until next 02:00 AM
            target = datetime.combine(now.date(), dt_time(2, 0))
            if target <= now:
                target += timedelta(days=1)
            
            wait_seconds = (target - now).total_seconds()
            logger.info(f"Next scheduled run at {target} (in {wait_seconds:.0f}s)")
            
            # Wait until target time or shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=wait_seconds)
                break # Shutdown signaled
            except asyncio.TimeoutError:
                # Time to trigger tasks
                logger.info("Triggering scheduled financial ingestion tasks...")
                
                # Push FX task
                await redis_client.rpush("tasks:financial_ingestion", json.dumps({
                    "type": "fx_ingestion",
                    "incremental": True
                }))
                
                # Push Holdings task
                await redis_client.rpush("tasks:financial_ingestion", json.dumps({
                    "type": "holdings_ingestion"
                }))
                
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            await asyncio.sleep(60)

# ── Worker Loop ──────────────────────────────────────────────────────────────

async def worker_loop():
    """Continuously poll Redis for tasks and process them."""
    logger.info("Worker loop started. Listening for tasks...")
    
    pool = await get_pool()
    
    # Task queues we listen to
    QUEUES = ["tasks:document_indexing", "tasks:financial_ingestion"]
    
    while not shutdown_event.is_set():
        try:
            result = await redis_client.blpop(QUEUES, timeout=5)
            
            if result:
                queue_name, task_data = result
                task = json.loads(task_data)
                
                if queue_name == "tasks:document_indexing":
                    await _handle_document_indexing(pool, task)
                elif queue_name == "tasks:financial_ingestion":
                    await _handle_financial_ingestion(pool, task)
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(1)

async def _handle_document_indexing(pool, task):
    document_id = task.get("document_id")
    file_path = task.get("file_path")
    owner_id = task.get("owner_id")
    
    logger.info(f"Processing document indexing: {document_id}")
    await process_document_worker(
        pool=pool,
        pinecone_index=pinecone_index,
        embed_model=connections.embed_model,
        document_id=document_id,
        file_path=file_path,
        owner_id=owner_id
    )

async def _handle_financial_ingestion(pool, task):
    task_type = task.get("type")
    logger.info(f"Processing financial ingestion: {task_type}")
    
    try:
        if task_type == "fx_ingestion":
            provider = BOIProvider()
            if task.get("incremental", True):
                await provider.ingest_incremental(pool)
            else:
                await provider.ingest(pool)
        
        elif task_type == "holdings_ingestion":
            provider = HoldingsProvider()
            await provider.ingest(pool)
            
        logger.info(f"Financial ingestion complete: {task_type}")
    except Exception as e:
        logger.error(f"Financial ingestion failed ({task_type}): {e}")

async def main():
    # 1. Setup Signal Handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)
    
    # 2. Initialize Connections & Models
    logger.info("Initializing worker connections...")
    load_ml_models()
    
    # 3. Queue one immediate FX update on startup (Developer friendly)
    await redis_client.rpush("tasks:financial_ingestion", json.dumps({
        "type": "fx_ingestion",
        "incremental": True
    }))
    
    # 4. Start Loops (Worker + Scheduler)
    logger.info("Starting loops...")
    await asyncio.gather(
        worker_loop(),
        scheduler_loop()
    )
    
    # 5. Cleanup
    logger.info("Cleaning up...")
    await close_pool()
    logger.info("Worker stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
