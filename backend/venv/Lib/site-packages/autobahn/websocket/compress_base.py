###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) typedef int GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

__all__ = (
    "PerMessageCompress",
    "PerMessageCompressOffer",
    "PerMessageCompressOfferAccept",
    "PerMessageCompressResponse",
    "PerMessageCompressResponseAccept",
)


class PerMessageCompressOffer:
    """
    Base class for WebSocket compression parameter client offers.
    """


class PerMessageCompressOfferAccept:
    """
    Base class for WebSocket compression parameter client offer accepts by the server.
    """


class PerMessageCompressResponse:
    """
    Base class for WebSocket compression parameter server responses.
    """


class PerMessageCompressResponseAccept:
    """
    Base class for WebSocket compression parameter server response accepts by client.
    """


class PerMessageCompress:
    """
    Base class for WebSocket compression negotiated parameters.

    Concrete subclasses (one per permessage-compress extension) implement the
    decompression interface used by the WebSocket protocol:

    - ``start_decompress_message(self)``
    - ``decompress_message_data(self, data, max_output_len=None)``
    - ``end_decompress_message(self)``

    Bounded-decompression contract for ``decompress_message_data``: when
    ``max_output_len`` is not ``None``, the call returns at most
    ``max_output_len`` octets of decompressed output and raises
    :class:`autobahn.exception.PayloadExceededError` if the input would produce
    more - it never silently truncates. ``max_output_len=None`` (the default)
    leaves decompression unbounded. Backends whose underlying library exposes an
    incremental output limit (deflate, bzip2) enforce the bound before fully
    inflating a frame; backends without one (snappy, brotli) inflate the frame
    (already bounded on the wire by ``maxFramePayloadSize``) and then check,
    a weaker but still-clean per-frame guarantee.
    """
