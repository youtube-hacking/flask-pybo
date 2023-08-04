import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum, IntegerField
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from tools.utils import get_client_ip
from ..forms import QuestionForm
from ..models import Question, Answer, Category, QuestionCount

logger = logging.getLogger('pybo')


class ListParam:
    def __init__(self, page, kw, so):
        self.page = page
        self.kw = kw
        self.so = so


def question_list(request, category_name):
    """
    pybo 목록출력
    """
    # 입력 파라미터
    page = request.GET.get('page', '1')  # 페이지
    kw = request.GET.get('kw', '')  # 검색어
    so = request.GET.get('so', 'recent')  # 정렬기준
    lp = ListParam(page, kw, so)
    request.session['lp'] = lp

    category = get_object_or_404(Category, name=category_name)
    _question_list = Question.objects.filter(category__name=category.name)

    # 검색
    if kw:
        _question_list = _question_list.filter(
            Q(subject__icontains=kw) |  # 제목검색
            Q(content__icontains=kw) |  # 내용검색
            Q(author__username__icontains=kw) |  # 질문 글쓴이검색
            Q(answer__content__icontains=kw) |  # 답변내용검색
            Q(answer__author__username__icontains=kw)  # 답글 글쓴이검색
        ).distinct()

    # 정렬
    _question_list = _question_list.annotate(
        num_voter=Count('voter', distinct=True)+Count('answer__voter', distinct=True),
        num_answer=Count('answer', distinct=True)+Count('comment', distinct=True)+Count('answer__comment', distinct=True))
    if so == 'recommend':
        _question_list = _question_list.order_by('-notice', '-num_voter', '-create_date')
    elif so == 'popular':
        _question_list = _question_list.order_by('-notice', '-num_answer', '-create_date')
    else:  # recent
        _question_list = _question_list.order_by('-notice', '-create_date')

    # 페이징처리
    paginator = Paginator(_question_list, 25)  # 페이지당 25개씩 보여주기
    page_obj = paginator.get_page(page)

    context = {'category': category, 'question_list': page_obj, 'page': page, 'kw': kw, 'so': so}
    return render(request, 'pybo/question_list.html', context)


@transaction.atomic
def question_detail(request, question_id):
    """
    pybo 내용 출력
    """
    page = request.GET.get('page', '1')  # 페이지
    so = request.GET.get('so', 'recommend')  # 답변정렬 (추천순: recommend, 최신순: recent)
    question = get_object_or_404(Question, pk=question_id)
    lp = request.session.get('lp')

    # 조회수
    ip = get_client_ip(request)
    cnt = QuestionCount.objects.filter(ip=ip, question=question).count()
    if cnt == 0:
        qc = QuestionCount(ip=ip, question=question)
        qc.save()
        if question.view_count:
            question.view_count += 1
        else:
            question.view_count = 1
        question.save()

    # 답변 정렬
    answer_list = Answer.objects.filter(question=question).annotate(num_voter=Count('voter'))
    if so == 'recommend':
        answer_list = answer_list.order_by('-num_voter', 'create_date')
    else:  # 시간순으로 정렬
        answer_list = answer_list.order_by('create_date', '-num_voter')

    # 답변 페이징
    paginator = Paginator(answer_list, 10)  # 페이지당 10개씩 보여주기
    page_obj = paginator.get_page(page)

    context = {'question': question, 'answer_list': page_obj, 'page': page,
               'so': so, 'category': question.category, 'lp': lp}
    return render(request, 'pybo/question_detail.html', context)


@login_required(login_url='common:login')
def question_create(request, category_name):
    """
    pybo 질문등록
    """
    category = get_object_or_404(Category, name=category_name)
    if request.method == "POST":
        form = QuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.author = request.user  # 추가한 속성 author 적용
            question.create_date = timezone.now()
            question.category = category
            question.save()
            return redirect('pybo:question_list', category_name)
    else:
        form = QuestionForm()
    context = {'form': form, 'category': category}
    return render(request, 'pybo/question_form.html', context)


@login_required(login_url='common:login')
def question_modify(request, question_id):
    """
    pybo 질문수정
    """
    question = get_object_or_404(Question, pk=question_id)
    if request.user != question.author and not request.user.is_staff:
        messages.error(request, '수정권한이 없습니다')
        return redirect(question.get_absolute_url())

    if request.method == "POST":
        form = QuestionForm(request.POST, instance=question)
        if form.is_valid():
            question = form.save(commit=False)
            question.modify_date = timezone.now()  # 수정일시 저장
            question.save()
            return redirect(question.get_absolute_url())
    else:
        form = QuestionForm(instance=question)
    context = {'form': form, 'category': question.category}
    return render(request, 'pybo/question_form.html', context)


@login_required(login_url='common:login')
def question_delete(request, question_id):
    """
    pybo 질문삭제
    """
    question = get_object_or_404(Question, pk=question_id)

    if question.answer_set.count() > 0:
        messages.error(request, '답변이 등록된 질문은 삭제할수 없습니다.')
        return redirect(question.get_absolute_url())

    if question.comment_set.count() > 0:
        messages.error(request, '댓글이 등록된 질문은 삭제할수 없습니다.')
        return redirect(question.get_absolute_url())

    if request.user != question.author and not request.user.is_staff:
        messages.error(request, '삭제권한이 없습니다')
        return redirect(question.get_absolute_url())

    question.delete()
    return redirect('pybo:question_list', question.category.name)