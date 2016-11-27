from __future__ import absolute_import
import sys
import operator as op
import types
import math
import re
import numpy as np
from functools import partial
from future.utils import iteritems, raise_from, raise_
from collections import defaultdict
import warnings

def make_jvp(fun, argnum=0):
    def jvp(*args, **kwargs):
        start_node, end_node = forward_pass(fun, args, kwargs, argnum)
        if not isnode(end_node) or start_node not in end_node.progenitors:
            warnings.warn("Output seems independent of input.")
            return lambda g : start_node.vspace.zeros(), end_node
        return lambda g : backward_pass(g, end_node, start_node), end_node
    return jvp

def forward_pass(fun, args, kwargs, argnum=0):
    args = list(args)
    start_node = new_progenitor(args[argnum])
    args[argnum] = start_node
    active_progenitors.add(start_node)
    try: end_node = fun(*args, **kwargs)
    except Exception as e: add_extra_error_message(e)
    active_progenitors.remove(start_node)
    return start_node, end_node

def backward_pass(g, end_node, start_node):
    outgrads = defaultdict(list)
    outgrads[end_node] = [cast_like(end_node.vspace, g)]
    assert_vspace_match(outgrads[end_node][0], end_node.vspace, None)
    tape = toposort(end_node, start_node)
    for node in tape:
        if node not in outgrads: continue
        cur_outgrad = vsum(node.vspace, *outgrads[node])
        function, args, kwargs, parents = node.recipe
        for argnum, parent in parents:
            raw_outgrad = function.grad(argnum, cur_outgrad, node, args, kwargs)
            outgrad = cast_like(parent.vspace, raw_outgrad)
            outgrads[parent].append(outgrad)
            assert_vspace_match(outgrad, parent.vspace, function)
    return cur_outgrad

active_progenitors = set()

class primitive(object):
    """
    Wraps a function so that its gradient can be specified and its invocation
    can be recorded. For examples, see the docs."""
    def __init__(self, fun):
        self.fun = fun
        self.grads = {}
        self.zero_grads = set()
        self.__name__ = fun.__name__
        self.__doc__ = fun.__doc__

    def __call__(self, *args, **kwargs):
        argvals = list(args)
        progenitors = set()
        parents = []
        for argnum, arg in enumerate(args):
            if isnode(arg):
                argvals[argnum] = arg.value
                if argnum in self.zero_grads: continue
                parents.append((argnum, arg))
                progenitors.update(arg.progenitors & active_progenitors)

        result_value = self.fun(*argvals, **kwargs)
        if progenitors:
            return new_node(result_value, (self, args, kwargs, parents), progenitors)
        else:
            return result_value

    def grad(self, argnum, outgrad, ans, args, kwargs):
        try:
            return self.grads[argnum](outgrad, ans, *args, **kwargs)
        except KeyError:
            if self.grads == {}:
                errstr = "Gradient of {0} not yet implemented."
            else:
                errstr = "Gradient of {0} w.r.t. arg number {1} not yet implemented."
            raise NotImplementedError(errstr.format(self.fun.__name__, argnum))

    def defgrad(self, gradmaker, argnum=0):
        gradmaker.__name__ = "VJP_{}_of_{}".format(argnum, self.__name__)
        self.grads[argnum] = gradmaker

    def defgrads(self, gradmaker, argnums):
        for argnum in argnums:
            self.defgrad(partial(gradmaker, argnum), argnum)

    def defgrad_is_zero(self, argnums=(0,)):
        for argnum in argnums:
            self.zero_grads.add(argnum)

    def __repr__(self):
        return self.__name__

    if sys.version_info >= (3,):
        def __get__(self, obj, objtype):
            return types.MethodType(self, obj)
    else:
        def __get__(self, obj, objtype):
            return types.MethodType(self, obj, objtype)

class nograd_primitive(primitive):
    def __call__(self, *args, **kwargs):
        argvals = map(getval, args)
        return self.fun(*argvals, **kwargs)

def new_progenitor(x):
    if isnode(x):
        node = new_node(x.value, (identity, (x,), {}, [(0, x)]), x.progenitors)
    else:
        node = new_node(x,       (identity, (x,), {}, []      ), set())
    node.progenitors = node.progenitors | {node}
    return node

def vsum(vspace, *args):
    if len(args) == 1 and type(getval(args[0])) != SparseObject:
        return args[0]
    else:
        return primitive_vsum(vspace, *args)

@primitive
def primitive_vsum(vspace, *args):
    ans = vspace.zeros()
    for arg in args:
        if type(arg) == SparseObject:
            ans = arg.mut_add(ans)
        else:
            ans = vspace.mut_add(ans, arg)
    return ans
primitive_vsum.grad = lambda arg, g, *args : g

@primitive
def identity(x) : return x
identity.defgrad(lambda g, ans, x : g)

class Node(object):
    __slots__ = ['value', 'recipe', 'progenitors', 'vspace']
    def __init__(self, value, recipe, progenitors):
        self.value = value
        self.recipe = recipe
        self.progenitors = progenitors
        self.vspace = vspace(value)

    def __bool__(self):
        return bool(self.value)

    __nonzero__ = __bool__

    def __str__(self):
        return "Autograd {0} with value {1} and {2} progenitors(s)".format(
            type(self).__name__, str(self.value), len(self.progenitors))


def toposort(end_node, start_node):
    def relevant_parents(node):
        return [parent for _, parent in node.recipe[3] if start_node in parent.progenitors]

    child_counts = {}
    stack = [end_node]
    while stack:
        node = stack.pop()
        if node in child_counts:
            child_counts[node] += 1
        else:
            child_counts[node] = 1
            stack.extend(relevant_parents(node))

    sorted_nodes = []
    childless_nodes = [end_node]
    while childless_nodes:
        node = childless_nodes.pop()
        sorted_nodes.append(node)
        for parent in relevant_parents(node):
            if child_counts[parent] == 1:
                childless_nodes.append(parent)
            else:
                child_counts[parent] -= 1

    return sorted_nodes

class VSpace(object):
    __slots__ = []
    def __init__(self, value):
        pass

    def zeros(self):
        assert False

    def mut_add(self, x, y):
        x += y
        return x

    def __eq__(self, other):
        return type(self) == type(other) and self.__dict__ == other.__dict__

    def __repr__(self):
        return "{}_{}".format(type(self).__name__, self.__dict__)

def flatten(value):
    return vspace(value).flatten(value)

node_type_mappings = {}
vspace_mappings = {}
node_types = set()
def register_node(node_type, value_type):
    node_types.add(node_type)
    node_type_mappings[value_type] = node_type
    node_type_mappings[node_type] = node_type

def register_vspace(vspace_maker, value_type):
    vspace_mappings[value_type] = vspace_maker

def new_node(value, recipe, progenitors):
    try:
        return node_type_mappings[type(value)](value, recipe, progenitors)
    except KeyError:
        raise TypeError("Can't differentiate w.r.t. type {}".format(type(value)))

def vspace(value):
    try:
        return vspace_mappings[type(value)](value)
    except KeyError:
        raise TypeError("Can't find vspace for type {}".format(type(value)))

class SparseObject(object):
    __slots__ = ['vs', 'mut_add']
    def __init__(self, vs, mut_add):
        self.vs = vs
        self.mut_add = mut_add

register_vspace(lambda x : x.vs, SparseObject)
register_node(Node, SparseObject)

def cast_like(target_vspace, x):
    if target_vspace == vspace(getval(x)):
        return x
    else:
        return target_vspace.cast(x)

def assert_vspace_match(x, expected_vspace, fun):
    assert expected_vspace == vspace(getval(x)), \
        "\nGrad of {} returned unexpected vector space" \
        "\nVector space is {}" \
        "\nExpected        {}".format(fun, vspace(getval(x)), expected_vspace)

@primitive
def cast(value, caster):
    return caster(value)
cast.defgrad(lambda g, *args: g)

def isnode(x): return type(x) in node_types
getval = lambda x : x.value if isnode(x) else x

class FloatNode(Node): pass

register_node(FloatNode, float)
register_node(FloatNode, complex)

def cast_to_float(x):
    if np.iscomplexobj(x):
        x = np.real(x)
    return float(x)

class FloatVSpace(VSpace):
    size = 1

    def zeros(self):
        return 0.0

    def cast(self, value):
        return cast(value, cast_to_float)

    def flatten(self, value):
        return np.array([value])

    def unflatten(self, value):
        return value[0]

register_vspace(FloatVSpace, float)

class ComplexVSpace(VSpace):
    value_types = [complex]
    def zeros(self):
        return 0.0j

    def cast(self, value):
        return cast(value, cast_to_complex)

register_vspace(ComplexVSpace, complex)

def cast_to_complex(value):
    if isinstance(value, np.ndarray):
        return complex(value[()])
    else:
        return complex(value)

if sys.version_info >= (3,):
    DIV = '__truediv__'
    RDIV = '__rtruediv__'
else:
    DIV = '__div__'
    RDIV = '__rdiv__'

differentiable_ops = ['__add__', '__sub__', '__mul__', '__pow__', '__mod__',
                      '__neg__', '__radd__', '__rsub__', '__rmul__', '__rpow__',
                      '__rmod__', DIV, RDIV]

nondifferentiable_ops = ['__eq__', '__ne__', '__gt__', '__ge__', '__lt__', '__le__',]
for float_op in differentiable_ops + nondifferentiable_ops:
    setattr(FloatNode, float_op, primitive(getattr(float, float_op)))

FloatNode.__dict__['__neg__'].defgrad(lambda g, ans, x : -g)


for comp_op in nondifferentiable_ops:
    FloatNode.__dict__[comp_op].defgrad_is_zero(argnums=(0, 1))

# These functions will get clobbered when autograd.numpy is imported.
# They're here to allow the use of autograd without numpy.
I = lambda g, *args: g
FloatNode.__dict__['__add__'].defgrad(I)
FloatNode.__dict__['__add__'].defgrad(I, argnum=1)
FloatNode.__dict__['__mul__'].defgrad(lambda g, ans, x, y : y * g)
FloatNode.__dict__['__mul__'].defgrad(lambda g, ans, x, y : x * g, argnum=1)
FloatNode.__dict__['__sub__'].defgrad(I)
FloatNode.__dict__['__sub__'].defgrad(lambda g, ans, x, y : -g, argnum=1)
FloatNode.__dict__[DIV].defgrad(lambda g, ans, x, y : g / y)
FloatNode.__dict__[DIV].defgrad(lambda g, ans, x, y : - g * x / y**2, argnum=1)
FloatNode.__dict__['__pow__'].defgrad(lambda g, ans, x, y : g * y * x ** (y - 1))
FloatNode.__dict__['__pow__'].defgrad(lambda g, ans, x, y : g * log(x) * x ** y, argnum=1)
FloatNode.__dict__['__mod__'].defgrad(I)
FloatNode.__dict__['__mod__'].defgrad(lambda g, ans, x, y : -g * floor(x/y), argnum=1)

log = primitive(math.log)
log.defgrad(lambda g, ans, x : g / x)
floor = primitive(math.floor)
floor.defgrad_is_zero()

def swap_args(grads):
    grad_0, grad_1 = grads[1], grads[0]
    return {0 : lambda g, ans, y, x : grad_0(g, ans, x, y),
            1 : lambda g, ans, y, x : grad_1(g, ans, x, y)}

FloatNode.__dict__['__radd__'].grads = swap_args(FloatNode.__dict__['__add__'].grads)
FloatNode.__dict__['__rmul__'].grads = swap_args(FloatNode.__dict__['__mul__'].grads)
FloatNode.__dict__['__rsub__'].grads = swap_args(FloatNode.__dict__['__sub__'].grads)
FloatNode.__dict__[RDIV].grads = swap_args(FloatNode.__dict__[DIV].grads)
FloatNode.__dict__['__rpow__'].grads = swap_args(FloatNode.__dict__['__pow__'].grads)
FloatNode.__dict__['__rmod__'].grads = swap_args(FloatNode.__dict__['__mod__'].grads)

class AutogradHint(Exception):
    def __init__(self, message, subexception_type=None, subexception_val=None):
        self.message = message
        self.subexception_type = subexception_type
        self.subexception_val = subexception_val

    def __str__(self):
        if self.subexception_type:
            return '{message}\nSub-exception:\n{name}: {str}'.format(
                message=self.message,
                name=self.subexception_type.__name__,
                str=self.subexception_type(self.subexception_val))
        else:
            return self.message

common_errors = [
    ((TypeError, r'float() argument must be a string or a number'),
        "This error *might* be caused by assigning into arrays, which autograd doesn't support."),
    ((TypeError, r"got an unexpected keyword argument '(?:dtype)|(?:out)'" ),
        "This error *might* be caused by importing numpy instead of autograd.numpy. \n"
        "Check that you have 'import autograd.numpy as np' instead of 'import numpy as np'."),
]

def check_common_errors(error_type, error_message):
    keys, vals = zip(*common_errors)
    match = lambda key: error_type == key[0] and len(re.findall(key[1], error_message)) != 0
    matches = map(match, keys)
    num_matches = sum(matches)

    if num_matches == 1:
        return vals[matches.index(True)]

def add_extra_error_message(e):
    etype, value, traceback = sys.exc_info()
    extra_message = check_common_errors(type(e), str(e))

    if extra_message:
        if sys.version_info >= (3,):
            raise_from(AutogradHint(extra_message), e)
        else:
            raise_(AutogradHint, (extra_message, etype, value), traceback)
    raise_(etype, value, traceback)
