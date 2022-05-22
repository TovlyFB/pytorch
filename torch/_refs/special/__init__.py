import torch

from torch import Tensor
import torch._prims as prims
import torch._prims.utils as utils
import torch._refs as refs

from typing import Sequence, Optional, Union, Callable, List, Tuple
from torch._decomp import register_decomposition
from torch._prims.utils import (
    TensorLike,
    TensorLikeType,
    Number,
    NumberType,
)
from torch._prims.wrappers import out_wrapper, elementwise_type_promotion_wrapper
from torch._refs import (
    _make_elementwise_unary_reference,
    _make_elementwise_binary_reference,
)

__all__ = [
    "i1",
    "i0e",
    "i1e",
    "logit",
    "xlog1py",
    "zeta",
]

i1 = _make_elementwise_unary_reference(
    prims.bessel_i1,
    type_promotion_kind=utils.ELEMENTWISE_TYPE_PROMOTION_KIND.INT_TO_FLOAT,
    aten_op=torch.ops.aten.special_i1,
)

i0e = _make_elementwise_unary_reference(
    prims.bessel_i0e,
    type_promotion_kind=utils.ELEMENTWISE_TYPE_PROMOTION_KIND.INT_TO_FLOAT,
    aten_op=torch.ops.aten.special_i0e,
)

i1e = _make_elementwise_unary_reference(
    prims.bessel_i1e,
    type_promotion_kind=utils.ELEMENTWISE_TYPE_PROMOTION_KIND.INT_TO_FLOAT,
    aten_op=torch.ops.aten.special_i1e,
)


@register_decomposition(torch.ops.aten.logit)
@out_wrapper
@elementwise_type_promotion_wrapper(
    type_promoting_args=("self",),
    type_promotion_kind=utils.ELEMENTWISE_TYPE_PROMOTION_KIND.INT_TO_FLOAT,
)
def logit(self: Tensor, eps: Optional[float] = None) -> Tensor:
    if eps is None:
        eps = -1.0
    lo = eps
    hi = 1 - eps
    self = torch.clamp(self, lo, hi)
    return (self / (1 - self)).log()


def _xlog1py(
    a: Union[TensorLikeType, NumberType], b: Union[TensorLikeType, NumberType]
):
    assert isinstance(a, TensorLike) or isinstance(b, TensorLike)

    # torch.xlog1py supports scalar inputs but torch.log does not.
    # TODO Add support for scalar inputs to refs.log (and other elementwise unary ops)
    if isinstance(a, TensorLike):
        if isinstance(b, Number):
            b = prims.scalar_tensor(b, dtype=a.dtype, device=a.device)
        elif utils.is_cpu_scalar_tensor(b):
            b = prims.device_put(b, device=a.device)
    elif isinstance(b, TensorLike):
        if isinstance(a, Number):
            a = prims.scalar_tensor(a, dtype=b.dtype, device=b.device)
        elif utils.is_cpu_scalar_tensor(a):
            a = prims.device_put(a, device=b.device)

    # TODO use refs.where after resolving issue #78050
    rhs = refs.where(refs.eq(a, 0), 0, refs.mul(a, refs.log1p(b)))
    return refs.where(refs.isnan(b), float("nan"), rhs)


# TODO add docstring
xlog1py = _make_elementwise_binary_reference(
    _xlog1py,
    type_promotion_kind=utils.ELEMENTWISE_TYPE_PROMOTION_KIND.INT_TO_FLOAT,
    aten_op=torch.ops.aten.special_xlog1py,
)

zeta = _make_elementwise_binary_reference(
    prims.zeta,
    type_promotion_kind=utils.ELEMENTWISE_TYPE_PROMOTION_KIND.INT_TO_FLOAT,
    aten_op=torch.ops.aten.special_zeta,
)
