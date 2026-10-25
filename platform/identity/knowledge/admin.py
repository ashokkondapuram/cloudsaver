"""Shared knowledge publication (no tenant-identifying content)."""
from uuid import uuid4

from identity.billing.domain import free_text
from identity.domain import IdentityError, NotFound, StaleVersion, iso, text, uuid_text
from identity.knowledge.privacy import screen, source
from datetime import timedelta

PUBLICATION_STATUSES = ('draft', 'published', 'deprecated', 'rejected')


class KnowledgeOps:
    @staticmethod
    def _knowledge_actor(actor):
        # Operator display names can change; Entra actor strings start with immutable oid.
        return actor['actor'].split(':', 1)[0][:120]
    def _publication_view(self, row):
        return {
            'id': str(row['id']), 'title': row['title'], 'summary': row['summary'], 'body': row['body'],
            'status': row['status'], 'quality_score': row.get('quality_score'),
            'version': row['version'], 'created_at': iso(row['created_at']), 'created_by': row['created_by'],
            'updated_at': iso(row['updated_at']), 'updated_by': row['updated_by'],
            'source_kind': row.get('source_kind'), 'source_url': row.get('source_url'),
            'applicability': row.get('applicability') or {}, 'reviews': row.get('reviews') or {},
        }

    def list_knowledge_publications(self, status=None, limit=50, cursor=None):
        offset, limit = self._page(cursor, limit)
        if status and status not in PUBLICATION_STATUSES:
            raise IdentityError('Choose a valid publication status.')
        with self.knowledge_store.transaction() as tx:
            rows = tx.list_knowledge_publications(status, limit + 1, offset)
        items = [self._publication_view(r) for r in rows[:limit]]
        return {'items': items, 'next_cursor': str(offset + limit) if len(rows) > limit else None}

    def create_knowledge_publication(self, payload, actor, request_id=None):
        title = text(payload.get('title'), 'Title', 200)
        summary = free_text(payload.get('summary'), 'Summary', 2000)
        body = free_text(payload.get('body'), 'Body', 8000)
        try:
            screen(title, summary, body)
            kind = payload.get('source_kind', 'synthetic')
            url = source(kind, payload.get('source_url'))
        except ValueError as exc:
            raise IdentityError(str(exc)) from None
        applicability = self._knowledge_applicability(payload.get('applicability', {}))
        now = self.now()
        row = {'id': str(uuid4()), 'title': title, 'summary': summary, 'body': body, 'status': 'draft',
               'quality_score': None, 'created_at': now, 'created_by': self._knowledge_actor(actor),
               'updated_at': now, 'updated_by': actor['actor'][:120], 'version': 1}
        row.update(source_kind=kind, source_url=url, applicability=applicability, reviews={})
        with self.knowledge_store.transaction() as tx:
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
            score = payload['quality_score']
            if type(score) is not int or not 0 <= score <= 100:
                raise IdentityError('Quality score must be between 0 and 100.')
            fields['quality_score'] = score
        now = self.now()
        with self.knowledge_store.transaction() as tx:
            current = tx.get_knowledge_publication(publication_id)
            if not current:
                raise NotFound('Publication not found.')
            if current['version'] != version:
                raise StaleVersion()
            if any(key in fields for key in ('title', 'summary', 'body')):
                if current['status'] != 'draft':
                    raise IdentityError('Published and terminal content is immutable. Create a new candidate.')
                try:
                    screen(*(fields.get(key, current[key]) for key in ('title', 'summary', 'body')))
                except ValueError as exc:
                    raise IdentityError(str(exc)) from None
                fields['reviews'] = {}
            if fields.get('status') == 'published':
                reviews = current.get('reviews') or {}
                if current['status'] != 'draft' or fields.get('reviews') == {} or not all(k in reviews for k in ('technical', 'privacy')):
                    raise IdentityError('Independent technical and privacy reviews are required before publication.', status=403)
                reviewers = {reviews[k]['actor'] for k in ('technical', 'privacy')}
                if len(reviewers) != 2 or current['created_by'] in reviewers:
                    raise IdentityError('Author and the two reviewers must be different people.', status=403)
            if current['status'] != 'draft' and fields.get('status') == 'draft':
                raise IdentityError('Terminal content cannot return to draft.')
            updated = tx.update_knowledge_publication(publication_id, version, dict(fields, updated_at=now, updated_by=actor['actor'][:120]))
            if updated is None:
                if not tx.get_knowledge_publication(publication_id):
                    raise NotFound('Publication not found.')
                raise StaleVersion()
            self._event(tx, actor, 'knowledge_publication_updated', details={'id': publication_id}, request_id=request_id)
        return self._publication_view(updated)

    @staticmethod
    def _knowledge_applicability(value):
        if not isinstance(value, dict) or set(value) - {'provider', 'service_category', 'rule_ids'}:
            raise IdentityError('Choose supported knowledge applicability fields.')
        provider = value.get('provider', '*')
        category = value.get('service_category', '*')
        rules = value.get('rule_ids', [])
        import re
        if provider not in ('*', 'azure', 'aws', 'gcp', 'kubernetes') or category not in ('*', 'storage', 'network', 'compute', 'database', 'application', 'other'):
            raise IdentityError('Choose a supported provider and service category.')
        if not isinstance(rules, list) or len(rules) > 30 or any(not isinstance(r, str) or not re.fullmatch('[A-Z0-9_]{1,80}', r) for r in rules):
            raise IdentityError('Choose valid published rule identifiers.')
        return dict(provider=provider, service_category=category, rule_ids=sorted(set(rules)))

    def review_knowledge_publication(self, publication_id, payload, actor, request_id=None):
        key = uuid_text(publication_id)
        version = self._version(payload)
        review = payload.get('review')
        role = {'technical': 'KnowledgeReviewer', 'privacy': 'PrivacyReviewer'}.get(review)
        if role is None or role not in actor.get('roles', []):
            raise IdentityError('The corresponding knowledge review role is required.', status=403)
        with self.knowledge_store.transaction() as tx:
            row = tx.get_knowledge_publication(key)
            if not row:
                raise NotFound('Publication not found.')
            if row['version'] != version:
                raise StaleVersion()
            reviews = dict(row.get('reviews') or {})
            reviewer = self._knowledge_actor(actor)
            if row['status'] != 'draft' or reviewer == row['created_by'] or any(r['actor'] == reviewer for r in reviews.values()):
                raise IdentityError('A different reviewer must review this draft.', status=403)
            screen(row['title'], row['summary'], row['body'])
            reviews[review] = {'actor': reviewer, 'at': iso(self.now())}
            updated = tx.update_knowledge_publication(key, version, dict(reviews=reviews,
                updated_at=self.now(), updated_by=actor['actor'][:120]))
            if not updated:
                raise StaleVersion()
            self._event(tx, actor, 'knowledge_reviewed', details={'id': key, 'review': review}, request_id=request_id)
        return self._publication_view(updated)

    def retrieve_knowledge(self, provider, service_category, rule_ids=()):
        requested = self._knowledge_applicability(dict(provider=provider, service_category=service_category, rule_ids=list(rule_ids)))
        with self.knowledge_store.transaction() as tx:
            rows = tx.list_knowledge_publications('published', 1000, 0)
        eligible = []
        for row in rows:
            match = row.get('applicability') or {}
            if not self._knowledge_current(row):
                continue
            if match.get('provider', '*') not in ('*', provider) or match.get('service_category', '*') not in ('*', service_category):
                continue
            if match.get('rule_ids') and not set(match['rule_ids']) & set(rule_ids):
                continue
            eligible.append(dict(publication_id=str(row['id']), version=row['version'], title=row['title'],
                                 guidance=row['summary'], source_url=row.get('source_url')))
        return {'items': eligible[:5], 'retrieval_limit': 5, 'candidate_count_limit': 1000}

    def knowledge_metrics(self):
        from collections import Counter
        with self.knowledge_store.transaction() as tx:
            rows = tx.list_knowledge_publications(None, 10001, 0)
        truncated = len(rows) > 10000
        rows = rows[:10000]
        counts = dict(Counter(row['status'] for row in rows))
        return dict(status_counts=counts, active_published=counts.get('published', 0),
                    fresh_published=sum(row['status'] == 'published' and self._knowledge_current(row) for row in rows),
                    as_of=iso(self.now()), truncated=truncated, quality_rate=None, citation_rate=None,
                    message='Publication counts are measured. Quality and citation rates are unavailable until evaluated.')

    def _knowledge_current(self, row):
        from identity.domain import parse_time
        reviews = row.get('reviews') or {}
        if not all(key in reviews for key in ('technical', 'privacy')):
            return False
        if row.get('source_kind') not in ('public_documentation', 'synthetic'):
            return False
        if len({reviews[key]['actor'] for key in ('technical', 'privacy')}) != 2:
            return False
        try:
            screen(row['title'], row['summary'], row['body'])
            return all(timedelta(0) <= self.now() - parse_time(reviews[key]['at']) <= timedelta(days=90)
                       for key in ('technical', 'privacy'))
        except (ValueError, IdentityError, KeyError):
            return False
