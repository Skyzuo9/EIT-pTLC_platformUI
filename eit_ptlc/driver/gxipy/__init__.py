#!/usr/bin/python
# -*- coding:utf-8 -*-
# -*-mode:python ; tab-width:4 -*- ex:set tabstop=4 shiftwidth=4 expandtab: -*-

import sys
import types

import numpy as _np

if not hasattr(_np, "compat"):
    _compat = types.ModuleType("numpy.compat")
    _compat.long = int
    sys.modules["numpy.compat"] = _compat
    _np.compat = _compat
elif not hasattr(_np.compat, "long"):
    _np.compat.long = int
    sys.modules.setdefault("numpy.compat", _np.compat)

from gxipy.gxiapi import *
from gxipy.gxidef import *


__all__ = ["gxwrapper", "dxwrapper", "gxiapi", "gxidef"]

__version__ = '2.0.2512.9261'
