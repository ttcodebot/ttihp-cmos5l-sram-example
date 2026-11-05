# SPDX-FileCopyrightText: © 2026 Tiny Tapeout B.V.
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

CMD_READ = 0b00
CMD_ADDR = 0b01
CMD_WRITE_LO = 0b10
CMD_WRITE_HI = 0b11


async def start(dut):
    # 10 us clock period (100 kHz)
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 1)


async def command(dut, cmd, value=0, byte_sel=0):
    # byte_sel may also carry the bank select (bit 1) for a set address command
    dut.ui_in.value = (cmd << 6) | byte_sel
    dut.uio_in.value = value
    await ClockCycles(dut.clk, 1)


async def write_word(dut, addr, word, bank=0):
    await command(dut, CMD_ADDR, addr, bank << 1)
    await command(dut, CMD_WRITE_LO, word & 0xFF)
    await command(dut, CMD_WRITE_HI, word >> 8)


async def read_word(dut, addr, bank=0):
    await command(dut, CMD_ADDR, addr, bank << 1)
    # The word is on uo_out after the third rising edge of clk, counting the one
    # that samples the set address command (see project.v). cocotb sees the values
    # from before the edge it just awaited, so wait for one edge more.
    for _ in range(3):
        await command(dut, CMD_READ)
    lo = dut.uo_out.value.to_unsigned()
    await command(dut, CMD_READ, byte_sel=1)
    hi = dut.uo_out.value.to_unsigned()
    return (hi << 8) | lo


@cocotb.test()
async def test_all_addresses(dut):
    await start(dut)
    # A unique word per address, so that a stuck or swapped address bit shows
    random.seed(1)
    words = random.sample(range(0x10000), 256)
    for addr, word in enumerate(words):
        await write_word(dut, addr, word)
    for addr, word in enumerate(words):
        got = await read_word(dut, addr)
        assert got == word, f"address {addr:#04x}: read {got:#06x}, expected {word:#06x}"


@cocotb.test()
async def test_byte_writes(dut):
    await start(dut)
    await write_word(dut, 0x55, 0xABCD)
    await command(dut, CMD_ADDR, 0x55)
    await command(dut, CMD_WRITE_HI, 0x12)
    assert await read_word(dut, 0x55) == 0x12CD
    await command(dut, CMD_ADDR, 0x55)
    await command(dut, CMD_WRITE_LO, 0x34)
    assert await read_word(dut, 0x55) == 0x1234


@cocotb.test()
async def test_output_holds_during_write(dut):
    await start(dut)
    await write_word(dut, 0x55, 0x1234)
    assert await read_word(dut, 0x55) == 0x1234
    await write_word(dut, 0xAA, 0x5678)
    # The write commands reach the SRAM one clock edge after they are sampled:
    # check uo_out once both writes have been done, before the next read
    for _ in range(2):
        await command(dut, CMD_READ)
    assert dut.uo_out.value.to_unsigned() == 0x34
    assert await read_word(dut, 0xAA) == 0x5678


@cocotb.test()
async def test_writes_ignored_during_reset(dut):
    await start(dut)
    await write_word(dut, 0x00, 0x0123)
    await write_word(dut, 0xAA, 0x5678)
    await command(dut, CMD_ADDR, 0xAA)
    dut.rst_n.value = 0
    await command(dut, CMD_WRITE_LO, 0xFF)
    await command(dut, CMD_WRITE_HI, 0xFF)
    dut.rst_n.value = 1
    await command(dut, CMD_READ)
    assert await read_word(dut, 0xAA) == 0x5678
    # The address register resets to 0, so an ungated write would land there
    assert await read_word(dut, 0x00) == 0x0123


@cocotb.test()
async def test_two_banks(dut):
    await start(dut)
    random.seed(2)
    w0 = random.sample(range(0x10000), 256)
    w1 = random.sample(range(0x10000), 256)
    for addr in range(256):
        await write_word(dut, addr, w0[addr], bank=0)
        await write_word(dut, addr, w1[addr], bank=1)
    for addr in range(256):
        got0 = await read_word(dut, addr, bank=0)
        got1 = await read_word(dut, addr, bank=1)
        assert got0 == w0[addr], f"bank 0 address {addr:#04x}: read {got0:#06x}, expected {w0[addr]:#06x}"
        assert got1 == w1[addr], f"bank 1 address {addr:#04x}: read {got1:#06x}, expected {w1[addr]:#06x}"
