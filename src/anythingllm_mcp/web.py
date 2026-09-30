"""AnythingLLM Web Admin - 文档管理界面"""

import json
import os
from starlette.applications import Starlette
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from anythingllm_mcp.anythingllm import AnythingLLMClient
from anythingllm_mcp.config import ANYTHINGLLM_BASE_URL, ANYTHINGLLM_API_KEY

_client: AnythingLLMClient | None = None

def get_client() -> AnythingLLMClient:
    global _client
    if _client is None:
        _client = AnythingLLMClient(ANYTHINGLLM_BASE_URL, ANYTHINGLLM_API_KEY)
    return _client

async def get_workspaces(request):
    try:
        workspaces = await get_client().list_workspaces()
        return JSONResponse({"workspaces": workspaces})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def get_documents(request):
    slug = request.query_params.get("slug", "")
    if not slug:
        return JSONResponse({"error": "slug required"}, status_code=400)
    try:
        docs = await get_client().list_documents(slug)
        return JSONResponse({"documents": docs, "slug": slug})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def delete_document(request):
    body = await request.json()
    workspace_id = body.get("workspaceId", "")
    document_id = body.get("documentId", "")
    if not workspace_id or not document_id:
        return JSONResponse({"error": "workspaceId and documentId required"}, status_code=400)
    try:
        await get_client().delete_document(workspace_id, document_id)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def get_workspace_detail(request):
    slug = request.path_params["slug"]
    try:
        detail = await get_client().get_workspace(slug)
        return JSONResponse(detail)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def serve_page(request):
    return FileResponse("web/index.html")

def create_app():
    middleware = [Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])]
    routes = [
        Route("/", serve_page),
        Route("/api/workspaces", get_workspaces),
        Route("/api/documents", get_documents),
        Route("/api/workspace/{slug}", get_workspace_detail),
        Route("/api/document/delete", delete_document, methods=["DELETE"]),
        Route("/web/{path:path}", lambda r: FileResponse(f"web/{r.path_params['path']}")),
    ]
    return Starlette(routes=routes, middleware=middleware)

def main():
    import uvicorn
    print("AnythingLLM Web Admin starting on http://localhost:8090")
    uvicorn.run("anythingllm_mcp.web:create_app", factory=True, host="0.0.0.0", port=8090)

if __name__ == "__main__":
    main()
