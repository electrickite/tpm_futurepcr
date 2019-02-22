#!/usr/bin/env python3
import sys
import os
import io
import hashlib
from pprint import pprint

from .event_log import *
from .tpm_constants import *
from .util import (hash_pecoff, read_current_pcr)

quiet = False

# h:s16 H:u16 l:s32 L:u32
# TPMv1: https://sources.debian.org/src/golang-github-coreos-go-tspi/0.1.1-2/tspi/tpm.go/?hl=44#L44

def main():
    SHA512_DIGEST_SIZE = 512 // 8

    NUM_PCRS = 24
    PCR_SIZE = hashlib.sha1().digest_size
    this_pcrs = {x: (b"\0" * PCR_SIZE) for x in range(NUM_PCRS)}
    this_pcrs.update({x: (b"\xFF" * PCR_SIZE) for x in [17,18,19,20,21,22]})
    next_pcrs = {**this_pcrs}

    for event in enum_log_entries():
        if not quiet:
            show_log_entry(event)
        idx = event["pcr_idx"]
        this_extend_value = event["pcr_extend_value"]
        next_extend_value = event["pcr_extend_value"]

        if event["event_type"] == TpmEventType.EFI_BOOT_SERVICES_APPLICATION:
            ed = parse_efi_bsa_event(event["event_data"])
            unix_path = device_path_to_unix_path(ed["device_path_vec"])
            file_hash = hash_pecoff(unix_path, "sha1")
            next_extend_value = file_hash
            pcr_value = this_pcrs[idx]
            pcr_value = hashlib.sha1(pcr_value + next_extend_value).digest()
            if not quiet:
                print("-- extending with coff hash --")
                print("file path =", unix_path)
                print("file hash =", to_hex(file_hash))
                print("this event extend value =", to_hex(this_extend_value))
                print("guessed extend value =", to_hex(next_extend_value))
                print("guessed next pcr value =", to_hex(pcr_value))

        this_pcrs[idx] = hashlib.sha1(this_pcrs[idx] + this_extend_value).digest()
        next_pcrs[idx] = hashlib.sha1(next_pcrs[idx] + next_extend_value).digest()
        if not quiet:
            print("--> after this event, PCR %d contains value %s" % (idx, to_hex(this_pcrs[idx])))
            print("--> after reboot, PCR %d will contain value %s" % (idx, to_hex(next_pcrs[idx])))
            print()

    # hack: systemd-boot doesn't generate a log entry when extending PCR 8
    if this_pcrs[8] == (b"\x00" * PCR_SIZE):
        this_pcrs[8] = read_current_pcr(8)
        next_pcrs[8] = this_pcrs[8]

    wanted_pcrs = range(NUM_PCRS)
    if quiet:
        with open("/dev/stdout", "wb") as fh:
            for x in wanted_pcrs:
                fh.write(next_pcrs[x])
    else:
        print("== Final PCR values ==")
        for x in range(NUM_PCRS):
            print("PCR %2d:" % x, to_hex(this_pcrs[x]), "|", to_hex(next_pcrs[x]))