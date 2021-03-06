#!/usr/bin/env python

# Copyright 2018 Blade M. Doyle
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#
# Routines for working with worker_stats records
#

import sys
import time
import requests
import json
from datetime import datetime

#import pprint
#pp = pprint.PrettyPrinter(indent=4)



from grinlib import lib
from grinlib import grin

from grinbase.model.blocks import Blocks
from grinbase.model.worker_shares import Worker_shares
from grinbase.model.worker_stats import Worker_stats
from grinbase.model.gps import Gps

# XXX TODO: Move to config
POOL_MIN_DIFF = 29
BATCHSZ = 100  # Bulk commit size
SECONDARY_SIZE = 29

# Calculate GPS for window[-1] for all graph sizes for a single worker and return it as a list of tuples [(edge_bits, gps_estimate ,), ...]
# window is a list of Worker_shares
def estimate_gps_for_all_sizes(worker, window):
    first_height = window[0].height
    last_height = window[-1].height
    print("estimate_gps_for_all_sizes: worker: {}".format(worker))
#    print("All Worker_shares in the window:")
#    pp.pprint(window)
    first_grin_block = Blocks.get_by_height(first_height)
    last_grin_block = Blocks.get_by_height(last_height)
    assert first_grin_block is not None, "Missing grin block at height: {}".format(first_height)
    assert last_grin_block is not None, "Missing grin block at height: {}".format(last_height)
    # Get the Worker_shares in the window *for this worker*
    this_workers_shares = [ws for ws in window if ws.worker == worker]
    print("This workers Shares records for the entire window: {}".format(len(this_workers_shares)))
    #pp.pprint(this_workers_shares)
    # Get a count of number of each valid solution size in this_workers_shares in this window
    valid_cnt = {}
    for worker_shares_rec in this_workers_shares:
        for shares in worker_shares_rec.shares:
            if shares.edge_bits not in valid_cnt:
                valid_cnt[shares.edge_bits] = 0
            valid_cnt[shares.edge_bits] += shares.valid
    #print("Valid Share Counts entire window for {}:".format(worker))
    #pp.pprint(valid_cnt)
    # Calcualte the gps for each graph size in the window
    all_gps = []
    for sz, cnt in valid_cnt.items():
        gps = lib.calculate_graph_rate(window[0].timestamp, window[-1].timestamp, cnt)
        all_gps.append((sz, gps, ))
    sys.stdout.flush()
    return all_gps


# Calculate worker stats for the specified height
# Return a list of Worker_stats object (one for each active worker)
# Raises AssertionError
def calculate(height, window_size):
    database = lib.get_db()
    grin_block = Blocks.get_by_height(height)
    assert grin_block is not None, "Missing grin block at height: {}".format(height)
    # Get all Worker_share records in the estimation window
    window = Worker_shares.get_by_height(height, window_size)
    # Get list of all workers who submitted shares in the window
    workers = list(set([share.worker for share in window]))
    # Create a new Worker_stats record for each of these workers
    print("Calcualte worker stats for height {}, workers {}".format(height, workers))
    new_stats = []
    for worker in workers:
        # Get this workers most recent worker_stats record (for running totals)
        last_stat = Worker_stats.get_latest_by_id(worker)
        if last_stat is None:
            # A new worker, initialize a last_stat for the previous block
            last_stat = Worker_stats(None, datetime.utcnow(), height-1, worker, 0, 0, 0, 0, 0, 0)
            new_stats.append(last_stat)
        # Calculate this workers stats data
        timestamp = grin_block.timestamp
        # Caclulate estimated GPS for all sizes with shares submitted
        all_gps = estimate_gps_for_all_sizes(worker, window)
        # Keep track of share totals - sum counts of all share sizes submitted for this block
        this_workers_shares = [ws for ws in window if ws.worker == worker]
        num_shares_processed = this_workers_shares[-1].num_shares()
        print("num_shares_processed={}".format(num_shares_processed))
        total_shares_processed = last_stat.total_shares_processed + num_shares_processed
        print("total_shares_processed={}".format(total_shares_processed))

        # XXX PERFORAMCE = could not get bulk_insert to work...
 
        stats = Worker_stats(
                id = None,
                height = height,
                timestamp = timestamp,
                worker = worker,
                shares_processed = num_shares_processed,
                total_shares_processed = total_shares_processed,
                grin_paid = 123, # XXX TODO
                total_grin_paid = 456, # XXX TODO
                balance = 1) # XXX TODO
        database.db.getSession().add(stats)
        database.db.getSession().commit()
        #print("AAA: Created Worker_stats with id={}".format(stats.id))
#        print("all_gps for worker {}:".format(worker))
#        pp.pprint(all_gps)
        for gps_est in all_gps:
            gps_rec = Gps(
                edge_bits = gps_est[0],
                gps = gps_est[1],
            )
            stats.gps.append(gps_rec)
            #print("AAA: Appended gps record to Worker_stats: {}".format(gps_rec))
#            gps_rec.worker_stats_id = stats.id,
#            database.db.getSession().add(gps_rec)
#        new_stats.append(stats)
        database.db.getSession().add(stats)
        database.db.getSession().commit()
    sys.stdout.flush()
    return new_stats

# Re-Caclulate worker stats from the specified height and commits to DB
# Return height of the last stat recalculated
# Raises AssertionError
def recalculate(start_height, avg_range):
    database = lib.get_db()
    height = start_height
    while height <= grin.blocking_get_current_height():
        old_stats = Worker_stats.get_by_height(height)
        new_stats = calculate(height, avg_range)
        for old_stat in old_stats:
            database.db.deleteDataObj(old_stat)
        for stats in new_stats:
            print("new/updated stats: {} ".format(stats))
            worker = stats.worker
            database.db.getSession().add(stats)
            if(height % BATCHSZ == 0):
                database.db.getSession().commit()
        height = height + 1
    database.db.getSession().commit()
