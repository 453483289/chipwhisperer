# -*- coding: utf-8 -*-
#
# Original Author: Ivan A-R <ivan@tuxotronic.org>
# Modified by: Colin O'Flynn (2017), NewAE Technology Inc.
# Original Project page: http://tuxotronic.org/wiki/projects/stm32loader
#
# This file is part of stm32loader.
#
# stm32loader is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 3, or (at your option) any later
# version.
#
# stm32loader is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with stm32loader; see the file COPYING3.  If not see
# <http://www.gnu.org/licenses/>.
#==========================================================================

import logging, os, time, traceback
from datetime import datetime
from naeusb import packuint32
from chipwhisperer.capture.utils.IntelHex import IntelHex

#From ST AN2606, See Section 50 (Device-dependent bootloader parameters), Page 244/268 on Rev 30 of document
#http://www.st.com/content/ccc/resource/technical/document/application_note/b9/9b/16/3a/12/1e/40/0c/CD00167594.pdf/files/CD00167594.pdf/jcr:content/translations/en.CD00167594.pdf

class STM32FDummy(object):
    signature = 0x000
    name = "Unknown STM32F"

class STM32F071(object):
    signature = 0x448
    name = "STM32F071xx/STM32F072xx"

class STM32F10xxx_LD(object):
    signature = 0x412
    name = "STM32F10xxx Low-density"

class STM32F10xxx_MD(object):
    signature = 0x410
    name = "STM32F10xxx Medium-density"

class STM32F10xxx_HD(object):
    signature = 0x414
    name = "STM32F10xxx High-density"

class STM32F10xxx_XL(object):
    signature = 0x416
    name = "STM32F10xxx XL-density"

class STM32F10xxx_MDV(object):
    signature = 0x420
    name = "STM32F10xxx Medium-density value line"

class STM32F10xxx_HDV(object):
    signature = 0x428
    name = "STM32F10xxx High-density value line"

class STM32F2(object):
    signature = 0x411
    name = "STM32F2"

class STM32F303cBC(object):
    signature = 0x422
    name = "STM32F302xB(C)/303xB(C)"

class STM32F40xxx(object):
    signature = 0x413
    name = "STM32F40xxx/41xxx"

supported_stm32f = [STM32F071(), STM32F10xxx_LD(), STM32F10xxx_MD(), STM32F10xxx_HD(), STM32F10xxx_XL(), STM32F10xxx_MDV(),
                    STM32F10xxx_HDV(), STM32F2(), STM32F303cBC(), STM32F40xxx()]

def print_fun(s):
    print s

class CmdException(Exception):
    pass

class STM32FSerial(object):
    """
    Class for programming an STM32F device using a serial port or ChipWhisperer-Serial
    """

    def __init__(self, cwserial=None, cwapi=None, spname=None, timeout=200):
        """
        Set the communications instance.
        """

        self._cwapi = cwapi
        self._cwserial = cwserial
        self._timeout = timeout
        self._chip = STM32FDummy()
        self.lastFlashedFile = "unknown"
        self.extended_erase = 0

        self._old_baud = None

#    def open(self, aport='/dev/tty.usbserial-ftCYPMYJ', abaudrate=115200):
#        self.sp = serial.Serial(
#            port=aport,
#            baudrate=abaudrate,  # baudrate
#            bytesize=8,  # number of databits
#            parity=serial.PARITY_EVEN,
#            stopbits=1,
#            xonxoff=0,  # don't enable software flow control
#            rtscts=0,  # don't enable RTS/CTS flow control
#            timeout=5  # set a timeout value, None for waiting forever
#        )

    def open_port(self):

        if self._cwserial:
            self._old_baud = self._cwserial._baud
            self._old_parity  = self._cwserial._parity
            self._old_stopbits = self._cwserial._stopbits
            self._old_timeout = self._cwserial.timeout
            self._cwserial.init(baud=38400, stopbits=1, parity="even")
            self._cwserial.timeout = 1000

            self.sp = self._cwserial
        else:
            raise NotImplementedError("CW-Serial is only supported method (for now)")

    def close_port(self):
        if self._old_baud:
            self._cwserial.init(baud=self._old_baud, stopbits=self._old_stopbits, parity=self._old_parity)
            self._cwserial.timeout = self._old_timeout
        self._old_baud = None
        self._old_parity = None
        self._old_stopbits = None

        if self._cwapi:
            self._cwapi.setParameter(['CW Extra Settings', 'Target IOn GPIO Mode', 'nRST: GPIO', 'Default'])

        if hasattr(self.sp, "close"):
            self.sp.close()

    def find(self):
        #setup serial port (or CW-serial port?)

        self.initChip()
        boot_version = self.cmdGet()
        chip_id = self.cmdGetID()

        for t in supported_stm32f:
            if chip_id == t.signature:
                logging.info("Detected known STMF32: %s"% t.name)
                self.setChip(t)
                return chip_id, t
        logging.warning("Detected unknown STM32F ID: 0x%03x"%chip_id)
        return chip_id, None

    def program(self, filename, memtype="flash", verify=True, logfunc=print_fun, waitfunc=None):
        """Programs memory type, dealing with opening filename as either .hex or .bin file"""
        self.lastFlashedFile = filename

        f = IntelHex(filename)

        fsize = f.maxaddr() - f.minaddr()
        fdata = f.tobinarray(start=f.minaddr())
        startaddr = f.minaddr()

        logging.info("Programming %d bytes at 0x%x", fsize, startaddr)

        logfunc("STM32F Programming %s..." % memtype)
        if waitfunc: waitfunc()
        self.writeMemory(startaddr, fdata)  # , erasePage=True

        logfunc("STM32F Reading %s..." % memtype)
        if waitfunc: waitfunc()
        # Do verify run
        rdata = self.readMemory(startaddr, len(fdata))

        for i in range(0, len(fdata)):
            if fdata[i] != rdata[i]:
                raise IOError("Verify failed at 0x%04x, %x != %x" % (i, fdata[i], rdata[i]))

        logfunc("Verified %s OK, %d bytes" % (memtype, fsize))

    def autoProgram(self, hexfile, erase=True, verify=True, logfunc=print_fun, waitfunc=None):
        # Helper function for programmer UI
        # Automatically program device with some error checking

        status = "FAILED"

        fname = hexfile
        if logfunc: logfunc("***Starting FLASH program process at %s***" % datetime.now().strftime('%H:%M:%S'))
        if waitfunc: waitfunc()
        if os.path.isfile(fname):
            if logfunc: logfunc("File %s last changed on %s" % (fname, time.ctime(os.path.getmtime(fname))))
            if waitfunc: waitfunc()

            try:
                if logfunc: logfunc("Entering Programming Mode")
                if waitfunc: waitfunc()
                self.open_port()
                self.find()

                if erase:
                    self.cmdEraseMemory()

                if waitfunc: waitfunc()
                self.program(hexfile, memtype="flash", verify=verify, logfunc=logfunc, waitfunc=waitfunc)
                if waitfunc: waitfunc()
                if logfunc: logfunc("Exiting programming mode")
                self.close_port()
                if waitfunc: waitfunc()

                status = "SUCCEEDED"

            except IOError, e:
                if logfunc: logfunc("FAILED: %s" % str(e))
                try:
                    self.close_port()
                except IOError:
                    pass

        else:
            if logfunc: logfunc("%s does not appear to be a file, check path" % fname)

        if logfunc: logfunc("***FLASH Program %s at %s***" % (status, datetime.now().strftime('%H:%M:%S')))

        return status == "SUCCEEDED"

    def setChip(self, chiptype):
        self._chip = chiptype

    def reset(self):
        self._cwapi.setParameter(['CW Extra Settings', 'Target IOn GPIO Mode', 'nRST: GPIO', 'Low'])
        time.sleep(0.1)
        self._cwapi.setParameter(['CW Extra Settings', 'Target IOn GPIO Mode', 'nRST: GPIO', 'High'])
        time.sleep(0.25)

    def set_boot(self, enter_bootloader):
        logging.info("Assuming appropriate BOOT pins set HIGH on STM32F Hardware now")


    def _wait_for_ask(self, info=""):
        # wait for ask
        try:
            ask = self.sp.read(1)[0]
        except:
            raise CmdException("Can't read port or timeout (%s)" % traceback.format_exc())
        else:
            if ask == 0x79:
                # ACK
                return 1
            else:
                if ask == 0x1F:
                    # NACK
                    raise CmdException("NACK " + info)
                else:
                    # Unknown responce
                    raise CmdException("Unknown response. " + info + ": " + hex(ask))

    def initChip(self):
        self.set_boot(True)
        self.reset()
        fails = 0
        while fails < 5:
            try:
                #First 2-times, try resetting. After that don't in case reset is causing garbage on lines.
                if fails < 2:
                    self.reset()
                self.sp.flush()
                self.sp.write("\x7F")
                return self._wait_for_ask("Syncro")
            except CmdException:
                logging.info("Sync failed with error %s, retrying..." % traceback.format_exc())
                fails += 1
        raise


    def releaseChip(self):
        self.set_boot(False)
        self.reset()

    def cmdGeneric(self, cmd):
        self.sp.write(chr(cmd))
        self.sp.write(chr(cmd ^ 0xFF))  # Control byte
        return self._wait_for_ask(hex(cmd))

    def cmdGet(self):
        if self.cmdGeneric(0x00):
            logging.info("*** Get command");
            len = self.sp.read(1)[0]
            version = self.sp.read(1)[0]
            logging.info("    Bootloader version: " + hex(version))
            #dat = map(lambda c: hex(self.sp.read(len))
            dat = map(hex, self.sp.read(len))
            if '0x44' in dat:
                self.extended_erase = 1
            logging.info("    Available commands: " + ", ".join(dat))
            self._wait_for_ask("0x00 end")
            return version
        else:
            raise CmdException("Get (0x00) failed")

    def cmdGetVersion(self):
        if self.cmdGeneric(0x01):
            logging.debug("*** GetVersion command")
            version = self.sp.read(1)[0]
            self.sp.read(2)
            self._wait_for_ask("0x01 end")
            logging.debug("    Bootloader version: " + hex(version))
            return version
        else:
            raise CmdException("GetVersion (0x01) failed")

    def cmdGetID(self):
        if self.cmdGeneric(0x02):
            logging.debug("*** GetID command")
            len = self.sp.read(1)[0]
            id = self.sp.read(len + 1)
            self._wait_for_ask("0x02 end")
            return reduce(lambda x, y: x * 0x100 + y, id)
        else:
            raise CmdException("GetID (0x02) failed")

    def _encode_addr(self, addr):
        byte3 = (addr >> 0) & 0xFF
        byte2 = (addr >> 8) & 0xFF
        byte1 = (addr >> 16) & 0xFF
        byte0 = (addr >> 24) & 0xFF
        crc = byte0 ^ byte1 ^ byte2 ^ byte3
        return (chr(byte0) + chr(byte1) + chr(byte2) + chr(byte3) + chr(crc))

    def cmdReadMemory(self, addr, lng):
        assert (lng <= 256)
        if self.cmdGeneric(0x11):
            logging.debug("*** ReadMemory command")
            self.sp.write(self._encode_addr(addr))
            self._wait_for_ask("0x11 address failed")
            N = (lng - 1) & 0xFF
            crc = N ^ 0xFF
            self.sp.write(chr(N) + chr(crc))
            self._wait_for_ask("0x11 length failed")
            return map(lambda c: c, self.sp.read(lng))
        else:
            raise CmdException("ReadMemory (0x11) failed")

    def cmdGo(self, addr):
        if self.cmdGeneric(0x21):
            logging.debug("*** Go command")
            self.sp.write(self._encode_addr(addr))
            self._wait_for_ask("0x21 go failed")
        else:
            raise CmdException("Go (0x21) failed")

    def cmdWriteMemory(self, addr, data):
        assert (len(data) <= 256)
        if self.cmdGeneric(0x31):
            logging.debug("*** Write memory command")
            self.sp.write(self._encode_addr(addr))
            self._wait_for_ask("0x31 address failed")
            # map(lambda c: hex(ord(c)), data)
            lng = (len(data) - 1) & 0xFF
            logging.debug("    %s bytes to write" % [lng + 1]);
            self.sp.write(chr(lng))  # len really
            crc = 0xFF
            for c in data:
                crc = crc ^ c
                self.sp.write(chr(c))
            self.sp.write(chr(crc))
            self._wait_for_ask("0x31 programming failed")
            logging.debug("    Write memory done")
        else:
            raise CmdException("Write memory (0x31) failed")

    def cmdEraseMemory(self, sectors=None):
        if self.extended_erase:
            return self.cmdExtendedEraseMemory()

        if self.cmdGeneric(0x43):
            logging.debug("*** Erase memory command")
            if sectors is None:
                # Global erase
                self.sp.write(chr(0xFF))
                self.sp.write(chr(0x00))
            else:
                # Sectors erase
                self.sp.write(chr((len(sectors) - 1) & 0xFF))
                crc = 0xFF
                for c in sectors:
                    crc = crc ^ c
                    self.sp.write(chr(c))
                self.sp.write(chr(crc))
            self._wait_for_ask("0x43 erasing failed")
            logging.info("    Erase memory done")
        else:
            raise CmdException("Erase memory (0x43) failed")

    def cmdExtendedEraseMemory(self):
        if self.cmdGeneric(0x44):
            logging.debug("*** Extended Erase memory command")
            # Global mass erase
            self.sp.write(chr(0xFF))
            self.sp.write(chr(0xFF))
            # Checksum
            self.sp.write(chr(0x00))
            tmp = self.sp.timeout
            self.sp.timeout = 30000
            print "Extended erase (0x44), this can take ten seconds or more"
            self._wait_for_ask("0x44 erasing failed")
            self.sp.timeout = tmp
            logging.info("    Extended Erase memory done")
        else:
            raise CmdException("Extended Erase memory (0x44) failed")

    def cmdWriteProtect(self, sectors):
        if self.cmdGeneric(0x63):
            logging.info("*** Write protect command")
            self.sp.write(chr((len(sectors) - 1) & 0xFF))
            crc = 0xFF
            for c in sectors:
                crc = crc ^ c
                self.sp.write(chr(c))
            self.sp.write(chr(crc))
            self._wait_for_ask("0x63 write protect failed")
            logging.info("    Write protect done")
        else:
            raise CmdException("Write Protect memory (0x63) failed")

    def cmdWriteUnprotect(self):
        if self.cmdGeneric(0x73):
            logging.info("*** Write Unprotect command")
            self._wait_for_ask("0x73 write unprotect failed")
            self._wait_for_ask("0x73 write unprotect 2 failed")
            logging.info("    Write Unprotect done")
        else:
            raise CmdException("Write Unprotect (0x73) failed")

    def cmdReadoutProtect(self):
        if self.cmdGeneric(0x82):
            logging.info("*** Readout protect command")
            self._wait_for_ask("0x82 readout protect failed")
            self._wait_for_ask("0x82 readout protect 2 failed")
            logging.info("    Read protect done")
        else:
            raise CmdException("Readout protect (0x82) failed")

    def cmdReadoutUnprotect(self):
        if self.cmdGeneric(0x92):
            logging.info("*** Readout Unprotect command")
            self._wait_for_ask("0x92 readout unprotect failed")
            self._wait_for_ask("0x92 readout unprotect 2 failed")
            logging.info("    Read Unprotect done")
        else:
            raise CmdException("Readout unprotect (0x92) failed")


            # Complex commands section

    def readMemory(self, addr, lng):
        data = []
        while lng > 256:
            logging.debug("Read %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
            data = data + self.cmdReadMemory(addr, 256)
            addr = addr + 256
            lng = lng - 256

        logging.debug("Read %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
        data = data + self.cmdReadMemory(addr, lng)
        return data

    def writeMemory(self, addr, data):
        lng = len(data)
        data = list(data)

        offs = 0
        while lng > 256:
            logging.debug("Write %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
            self.cmdWriteMemory(addr, data[offs:offs + 256])
            offs = offs + 256
            addr = addr + 256
            lng = lng - 256
        logging.debug("Write %(len)d bytes at 0x%(addr)X" % {'addr': addr, 'len': 256})
        self.cmdWriteMemory(addr, data[offs:offs + lng] + ([0xFF] * (256 - lng)))

        def __init__(self):
            pass