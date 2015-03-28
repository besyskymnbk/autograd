from __future__ import absolute_import
import numpy.linalg as npla
from .numpy_wrapper import wrap_namespace, dot

wrap_namespace(npla.__dict__, globals())

inv.defgrad(  lambda ans, x    : lambda g : -dot(dot(ans.T, g), ans.T))
det.defgrad(  lambda ans, x    : lambda g : g * ans * inv(x).T)
solve.defgrad(lambda ans, a, b : lambda g : -dot(dot(inv(a).T, g), ans.T))
solve.defgrad(lambda ans, a, b : lambda g : dot(inv(a).T, g), argnum=1)