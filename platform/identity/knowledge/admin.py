"""Shared knowledge publication (no tenant-identifying content)."""
from uuid import uuid4

from identity.billing.domain import free_text
from identity.domain import IdentityError, NotFound, StaleVersion, iso, text, uuid_text

PUBLICATION_STATUSES = ('draft', 'published', 'deprecated', 'rejected')


class KnowledgeOps:
    def _publication_view(self, row):
        return {
            'id': str(row['id']), 'title': row['title'], 'summary': row['summary'], 'body': row['body'],
            'status': row['status'], 'quality_score': row.get('quality_score'),
            'version': row['version'], 'created_at': iso(row['created_at']), 'created_by': row['created_by'],
            'updated_at': iso(row['updated_at']), 'updated_by': row['updated_by'],
        }

    def list_knowledge_publications(self, status=None, limit=50, cursor=None):
        offset, limit = self._page(cursor, limit)
        if status and status not in PUBLICATION_STATUSES:
            raise IdentityError('Choose a valid publication status.')
        with self.store.transaction() as tx:
            rows = tx.list_knowledge_publications(status, limit + 1, offset)
        items = [self._publication_view(r) for r in rows[:limit]]
        return {'items': items, 'next_cursor': str(offset + limit) if len(rows) > limit else None}

    def create_knowledge_publication(self, payload, actor, request_id=None):
        title = text(payload.get('title'), 'Title', 200)
        summary = free_text(payload.get('summary'), 'Summary', 2000)
        body = free_text(payload.get('body'), 'Body', 8000)
        now = self.now()
        row = {'id': str(uuid4()), 'title': title, 'summary': summary, 'body': body, 'status': 'draft',
               'quality_score': None, 'created_at': now, 'created_by': actor['actor'][:120],
               'updated_at': now, 'updated_by': actor['actor'][:120], 'version': 1}
        with self.store.transaction() as tx:
            tx.insert_knowledge_publication(row)
            self._event(tx, actor, 'knowledge_publication_created', details={'id': row['id']}, request_id=request_id)
        return self._publication_view(row)

    def update_knowledge_publication(self, publication_id, payload, actor, request_id=None):
        publication_id = uuid_text(publication_id)
        version = self._version(payload)
        fields = {}
        if payload.get('title') is not None:
            fields['title'] = text(payload['title'], 'Title', 200)
        if payload.get('summary') is not None:
            fields['summary'] = free_text(payload['summary'], 'Summary', 2000)
        if payload.get('body') is not None:
            fields['body'] = free_text(payload['body'], 'Body', 8000)
        if payload.get('status') is not None:
            status = payload['status']
            if status not in PUBLICATION_STATUSES:
                raise IdentityError('Choose a valid publication status.')
            fields['status'] = status
        if 'quality_score' in payload and payload['quality_score'] is not None:
            score = int(payload['quality_score'])
            if not 0 <= score <= 100:
                raise IdentityError('Quality score must be between 0 and 100.')
            fields['quality_score'] = score
        now = self.now()
        with self.store.transaction() as tx:
            updated = tx.update_knowledge_publication(publication_id, version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if updated is None:
                if not tx.get_knowledge_publication(publication_id):
                    raise NotFound('Publication not found.')
                raise StaleVersion()
            self._event(tx, actor, 'knowledge_publication_updated', details={'id': publication_id}, request_id=request_id)
        return self._publication_view(updated)
