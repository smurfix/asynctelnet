import pytest

@pytest.fixture(params=[
    pytest.param(('asyncio', {}), id='asyncio'),
    pytest.param(('trio', {}), id='trio'),
])
def anyio_backend(request):
    return request.param
