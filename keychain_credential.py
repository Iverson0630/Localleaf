#!/usr/bin/env python3
"""LocalLeaf's minimal macOS Keychain credential helper for Overleaf Git."""
import ctypes
from pathlib import Path
import sys

SERVICE = b'LocalLeaf Overleaf Git'
ACCOUNT = b'git.overleaf.com'
NOT_FOUND = -25300


def _libraries():
    security = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/Security.framework/Security')
    core = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    security.SecKeychainItemDelete.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    core.CFRelease.argtypes = [ctypes.c_void_p]
    return security, core


def _find():
    security, core = _libraries()
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None, len(SERVICE), SERVICE, len(ACCOUNT), ACCOUNT,
        ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
    return security, core, status, length, data, item


def get_token():
    security, core, status, length, data, item = _find()
    if status == NOT_FOUND:
        return None
    if status != 0:
        raise RuntimeError(f'Keychain read failed ({status})')
    try:
        return ctypes.string_at(data, length.value).decode('utf-8')
    finally:
        security.SecKeychainItemFreeContent(None, data)
        if item:
            core.CFRelease(item)


def set_token(token):
    value = token.encode('utf-8')
    security, core, status, length, data, item = _find()
    if status == 0:
        security.SecKeychainItemFreeContent(None, data)
        try:
            result = security.SecKeychainItemModifyAttributesAndData(item, None, len(value), value)
        finally:
            core.CFRelease(item)
    elif status == NOT_FOUND:
        result = security.SecKeychainAddGenericPassword(
            None, len(SERVICE), SERVICE, len(ACCOUNT), ACCOUNT, len(value), value, None)
    else:
        result = status
    if result != 0:
        raise RuntimeError(f'Keychain write failed ({result})')


def delete_token():
    security, core, status, length, data, item = _find()
    if status == NOT_FOUND:
        return
    if status != 0:
        raise RuntimeError(f'Keychain lookup failed ({status})')
    security.SecKeychainItemFreeContent(None, data)
    try:
        result = security.SecKeychainItemDelete(item)
    finally:
        core.CFRelease(item)
    if result not in (0, NOT_FOUND):
        raise RuntimeError(f'Keychain delete failed ({result})')


def helper(operation):
    fields = {}
    for line in sys.stdin:
        line = line.rstrip('\n')
        if not line:
            break
        if '=' in line:
            key, value = line.split('=', 1)
            fields[key] = value
    if fields.get('host') != 'git.overleaf.com':
        return
    if operation == 'get':
        token = get_token()
        if token:
            print('username=git')
            print('password=' + token)
    elif operation == 'store' and fields.get('password'):
        set_token(fields['password'])
    elif operation == 'erase':
        delete_token()


if __name__ == '__main__':
    helper(sys.argv[1] if len(sys.argv) > 1 else 'get')
