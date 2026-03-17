"""Douyin X-Bogus helper.

This file is adapted from:
https://github.com/Evil0ctal/Douyin_TikTok_Download_API

Original project license: Apache License 2.0
The implementation here is trimmed to the minimal code needed by video2prompt.
"""

from __future__ import annotations

import base64
import hashlib
import time


class XBogus:
    def __init__(self, user_agent: str | None = None) -> None:
        self.array = [
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            10,
            11,
            12,
            13,
            14,
            15,
        ]
        self.character = "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe="
        self.ua_key = b"\x00\x01\x0c"
        self.user_agent = (
            user_agent
            if user_agent is not None and user_agent != ""
            else (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
            )
        )

    def md5_str_to_array(self, md5_str: str | list[int]) -> list[int]:
        if isinstance(md5_str, str) and len(md5_str) > 32:
            return [ord(char) for char in md5_str]

        array: list[int] = []
        idx = 0
        while idx < len(md5_str):
            array.append((self.array[ord(md5_str[idx])] << 4) | self.array[ord(md5_str[idx + 1])])
            idx += 2
        return array

    def md5_encrypt(self, url_path: str) -> list[int]:
        return self.md5_str_to_array(self.md5(self.md5_str_to_array(self.md5(url_path))))

    def md5(self, input_data: str | list[int]) -> str:
        if isinstance(input_data, str):
            array = self.md5_str_to_array(input_data)
        elif isinstance(input_data, list):
            array = input_data
        else:
            raise ValueError("Invalid input type. Expected str or list.")

        md5_hash = hashlib.md5()
        md5_hash.update(bytes(array))
        return md5_hash.hexdigest()

    @staticmethod
    def _encoding_conversion(
        a: int,
        b: int,
        c: int,
        e: int,
        d: int,
        t: int,
        f: int,
        r: int,
        n: int,
        o: int,
        i: int,
        underscore: int,
        x: int,
        u: int,
        s: int,
        l: int,
        v: int,
        h: int,
        p: int,
    ) -> str:
        values = [a, int(i), b, underscore, c, x, e, u, d, s, t, l, f, v, r, h, n, p, o]
        return bytes(values).decode("ISO-8859-1")

    @staticmethod
    def _encoding_conversion2(a: int, b: int, c: str) -> str:
        return chr(a) + chr(b) + c

    @staticmethod
    def _rc4_encrypt(key: bytes, data: bytes) -> bytearray:
        s_box = list(range(256))
        j = 0
        encrypted_data = bytearray()

        for i in range(256):
            j = (j + s_box[i] + key[i % len(key)]) % 256
            s_box[i], s_box[j] = s_box[j], s_box[i]

        i = j = 0
        for byte in data:
            i = (i + 1) % 256
            j = (j + s_box[i]) % 256
            s_box[i], s_box[j] = s_box[j], s_box[i]
            encrypted_data.append(byte ^ s_box[(s_box[i] + s_box[j]) % 256])

        return encrypted_data

    def _calculation(self, a1: int, a2: int, a3: int) -> str:
        merged = ((a1 & 255) << 16) | ((a2 & 255) << 8) | a3
        return (
            self.character[(merged & 16515072) >> 18]
            + self.character[(merged & 258048) >> 12]
            + self.character[(merged & 4032) >> 6]
            + self.character[merged & 63]
        )

    def get_xbogus(self, query_string: str) -> str:
        array1 = self.md5_str_to_array(
            self.md5(
                base64.b64encode(self._rc4_encrypt(self.ua_key, self.user_agent.encode("ISO-8859-1"))).decode(
                    "ISO-8859-1"
                )
            )
        )
        array2 = self.md5_str_to_array(self.md5(self.md5_str_to_array("d41d8cd98f00b204e9800998ecf8427e")))
        url_path_array = self.md5_encrypt(query_string)

        timer = int(time.time())
        ct = 536919696
        xb_value = ""
        new_array = [
            64,
            int(0.00390625),
            1,
            12,
            url_path_array[14],
            url_path_array[15],
            array2[14],
            array2[15],
            array1[14],
            array1[15],
            timer >> 24 & 255,
            timer >> 16 & 255,
            timer >> 8 & 255,
            timer & 255,
            ct >> 24 & 255,
            ct >> 16 & 255,
            ct >> 8 & 255,
            ct & 255,
        ]
        xor_result = new_array[0]
        for item in new_array[1:]:
            xor_result ^= item
        new_array.append(xor_result)

        array3: list[int] = []
        array4: list[int] = []
        idx = 0
        while idx < len(new_array):
            array3.append(new_array[idx])
            if idx + 1 < len(new_array):
                array4.append(new_array[idx + 1])
            idx += 2

        merge_array = array3 + array4
        garbled_code = self._encoding_conversion2(
            2,
            255,
            self._rc4_encrypt(
                "ÿ".encode("ISO-8859-1"),
                self._encoding_conversion(*merge_array).encode("ISO-8859-1"),
            ).decode("ISO-8859-1"),
        )

        idx = 0
        while idx < len(garbled_code):
            xb_value += self._calculation(
                ord(garbled_code[idx]),
                ord(garbled_code[idx + 1]),
                ord(garbled_code[idx + 2]),
            )
            idx += 3
        return xb_value
