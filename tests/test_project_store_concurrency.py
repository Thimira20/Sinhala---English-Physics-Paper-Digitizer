import asyncio
import pytest
from core.project_store import ProjectStore
from core.models import Page

@pytest.mark.asyncio
async def test_concurrent_edits_no_lost_updates(tmp_path):
    store = ProjectStore(base_dir=tmp_path)
    proj = store.create_project("c")
    for i in range(1, 21):
        proj.pages[str(i)] = Page(index=i, source_file="s", work_file="w", thumb_file="t")
    store.save_project_sync(proj)

    async def bump(i):
        async with store.edit(proj.id) as p:
            p.pages[str(i)].markdown = f"page {i}"

    await asyncio.gather(*(bump(i) for i in range(1, 21)))

    final = store.load_project(proj.id)
    assert all(final.pages[str(i)].markdown == f"page {i}" for i in range(1, 21))
